package com.ruanzhu.doorhandle.module.ai.model;

import io.agentscope.core.model.*;
import io.agentscope.core.message.TextBlock;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.model.transport.HttpTransportException;
import io.agentscope.core.message.ThinkingBlock;
import io.agentscope.core.message.ToolUseBlock;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.List;
import java.util.concurrent.TimeoutException;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ManagedAgentModelTest {
    @Test void boundedIoCapacityCanFallbackWithoutLeakingExecutorDetails() {
        var primary=model();var fallback=model();
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.error(new java.util.concurrent.RejectedExecutionException("private executor details")));
        var reply=answer("backup");when(fallback.stream(anyList(),anyList(),any())).thenReturn(Flux.just(reply));
        assertThat(route(new AgentModelProperties(),primary,fallback).stream(List.of(),List.of(),null).blockLast()).isSameAs(reply);
        verify(fallback,times(1)).stream(anyList(),anyList(),any());
    }
    private Model model() { var model = mock(Model.class); when(model.getModelName()).thenReturn("test-model"); return model; }
    private ChatResponse answer(String text) { return ChatResponse.builder().content(List.of(TextBlock.builder().text(text).build())).build(); }
    private ModelCircuit circuit() { return new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5)); }
    private ManagedAgentModel route(AgentModelProperties settings, Model... models) {
        var candidates = new java.util.ArrayList<ManagedAgentModel.Candidate>();
        for (int i = 0; i < models.length; i++) candidates.add(new ManagedAgentModel.Candidate("model-" + i, models[i], circuit()));
        return new ManagedAgentModel(candidates, null, settings, true);
    }
    @Test void fallsBackOnTransientFailureOnlyBeforeOutputAndSanitizesErrors() {
        var primary = model(); var fallback = model();
        var answer = ChatResponse.builder().id("r1").content(List.of(TextBlock.builder().text("备用回复").build())).build();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new TimeoutException()));
        when(fallback.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer));
        assertThat(new ManagedAgentModel("primary", primary, fallback).stream(List.of(), List.of(), null).collectList().block()).containsExactly(answer);
        verify(fallback).stream(anyList(), anyList(), any());
    }
    @Test void neverFallsBackAfterPartialOutputOrForInvalidCredentials() {
        var primary = model(); var fallback = model();
        var chunk = ChatResponse.builder().id("r1").content(List.of(TextBlock.builder().text("partial").build())).build();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(chunk), Flux.error(new TimeoutException())));
        assertThatThrownBy(() -> new ManagedAgentModel("primary", primary, fallback).stream(List.of(), List.of(), null).collectList().block())
                .isInstanceOf(IllegalStateException.class);
        verifyNoInteractions(fallback);
        when(primary.stream(anyList(), anyList(), any())).thenThrow(new IllegalArgumentException("invalid secret-key"));
        assertThatThrownBy(() -> new ManagedAgentModel("primary", primary, fallback).stream(List.of(), List.of(), null).blockLast())
                .hasMessageNotContaining("secret-key").hasCause(null);
        verifyNoInteractions(fallback);
    }
    @Test void configuredExecutionBudgetCannotBeOverwrittenByAgentDefaults() {
        var primary = model();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("ok").build())).build()));
        var policy = GenerateOptions.builder().maxTokens(256).executionConfig(ExecutionConfig.builder().maxAttempts(1).build()).build();
        var caller = GenerateOptions.builder().maxTokens(4096).stream(false)
                .executionConfig(ExecutionConfig.builder().maxAttempts(3).build()).build();
        new ManagedAgentModel("primary", primary, null, policy).stream(List.of(), List.of(), caller).blockLast();
        var captured = org.mockito.ArgumentCaptor.forClass(GenerateOptions.class);
        verify(primary).stream(anyList(), anyList(), captured.capture());
        assertThat(captured.getValue().getMaxTokens()).isEqualTo(256);
        assertThat(captured.getValue().getExecutionConfig().getMaxAttempts()).isEqualTo(1);
        assertThat(captured.getValue().getStream()).isFalse();
    }

    @Test void chainsThroughQuotaAndServerFailureAndPreservesTheOriginalRequest() {
        var primary = model(); var second = model(); var third = model();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("fixture", 429, "{\"code\":\"insufficient_quota\"}")));
        when(second.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("fixture", 503, "unavailable")));
        var answer = answer("third");
        when(third.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer));
        var history = List.<io.agentscope.core.message.Msg>of(new io.agentscope.core.message.UserMessage("question"));
        var tools = List.<ToolSchema>of();
        var options = GenerateOptions.builder().stream(true).build();
        assertThat(route(new AgentModelProperties(), primary, second, third).stream(history, tools, options).collectList().block()).containsExactly(answer);
        verify(third).stream(same(history), same(tools), same(options));
    }

    @Test void cancelsSlowPrimaryAndIgnoresEmptyMetadataWhenTimingFirstContent() {
        var primary = model(); var fallback = model(); var cancelled = new AtomicBoolean();
        var empty = ChatResponse.builder().content(List.of()).build();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(empty), Flux.<ChatResponse>never()).doOnCancel(() -> cancelled.set(true)));
        var answer = answer("backup");
        when(fallback.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer));
        var settings = new AgentModelProperties(); settings.setFirstTokenTimeout(Duration.ofMillis(50));
        assertThat(route(settings, primary, fallback).stream(List.of(), List.of(), null).collectList().block(Duration.ofSeconds(3))).containsExactly(answer);
        assertThat(cancelled).isTrue();
    }

    @Test void firstContentDeadlineDoesNotBecomeAnInterTokenDeadline() {
        var primary = model(); var fallback = model();
        var settings = new AgentModelProperties(); settings.setFirstTokenTimeout(Duration.ofMillis(30));
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(answer("first")), Mono.delay(Duration.ofMillis(100)).map(t -> answer("last"))));
        assertThat(route(settings, primary, fallback).stream(List.of(), List.of(), null).collectList().block(Duration.ofSeconds(3))).hasSize(2);
        verifyNoInteractions(fallback);
    }

    @Test void boundsAStalledStreamAfterContentWithoutSwitching() {
        var primary = model(); var fallback = model(); var cancelled = new AtomicBoolean();
        var settings = new AgentModelProperties(); settings.setTimeout(Duration.ofMillis(100)); settings.setFirstTokenTimeout(Duration.ofMillis(30));
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(answer("partial")), Flux.<ChatResponse>never()).doOnCancel(() -> cancelled.set(true)));
        assertThatThrownBy(() -> route(settings, primary, fallback).stream(List.of(), List.of(), null).collectList().block(Duration.ofSeconds(3)))
                .isInstanceOf(IllegalStateException.class).hasCause(null);
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(1)).untilTrue(cancelled);
        verifyNoInteractions(fallback);
    }

    @Test void skipsCoolingModelAcrossDifferentWrappersAndReportsQuotaState() {
        var primary = model(); var fallback = model(); var shared = circuit();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("secret", 402, "secret")));
        when(fallback.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer("backup")));
        var candidates = List.of(new ManagedAgentModel.Candidate("primary", primary, shared), new ManagedAgentModel.Candidate("backup", fallback, circuit()));
        for (int i = 0; i < 2; i++) new ManagedAgentModel(candidates, null, new AgentModelProperties(), true).stream(List.of(), List.of(), null).blockLast();
        verify(primary, times(1)).stream(anyList(), anyList(), any());
        verify(fallback, times(2)).stream(anyList(), anyList(), any());
        assertThat(shared.health().state()).isEqualTo("OPEN"); assertThat(shared.health().lastFailure()).isEqualTo("QUOTA");
    }

    @Test void thinkingAndToolOutputAlsoPreventCrossModelReplay() {
        for (var block : List.of(ThinkingBlock.builder().thinking("thinking").build(), new ToolUseBlock("call", "lookup", Map.of()))) {
            var primary = model(); var fallback = model();
            when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(ChatResponse.builder().content(List.of(block)).build()), Flux.error(new TimeoutException())));
            assertThatThrownBy(() -> route(new AgentModelProperties(), primary, fallback).stream(List.of(), List.of(), null).blockLast()).isInstanceOf(IllegalStateException.class);
            verifyNoInteractions(fallback);
        }
    }

    @Test void emptyCompletedResponseUsesBackupButBadRequestsDoNot() {
        var primary = model(); var fallback = model();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.empty());
        when(fallback.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer("backup")));
        route(new AgentModelProperties(), primary, fallback).stream(List.of(), List.of(), null).blockLast();
        clearInvocations(fallback);
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("bad", 400, "invalid schema secret")));
        assertThatThrownBy(() -> route(new AgentModelProperties(), primary, fallback).stream(List.of(), List.of(), null).blockLast()).hasMessageNotContaining("secret").hasCause(null);
        verifyNoInteractions(fallback);
    }

    @Test void allCandidatesUnavailableTerminatesWithoutLoopingOrLeakingErrors() {
        var primary = model(); var second = model();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("secret-1", 402, "secret-1")));
        when(second.stream(anyList(), anyList(), any())).thenReturn(Flux.error(new HttpTransportException("secret-2", 503, "secret-2")));
        var route = route(new AgentModelProperties(), primary, second);
        for (int i = 0; i < 3; i++) assertThatThrownBy(() -> route.stream(List.of(), List.of(), null).blockLast()).hasMessageNotContaining("secret").hasCause(null);
        verify(primary, times(1)).stream(anyList(), anyList(), any()); verify(second, times(2)).stream(anyList(), anyList(), any());
    }

    @Test void continuousOutputDoesNotExtendTheTotalBudget() {
        var primary = model(); var fallback = model(); var count = new java.util.concurrent.atomic.AtomicInteger();
        var settings = new AgentModelProperties(); settings.setFirstTokenTimeout(Duration.ofMillis(100)); settings.setTimeout(Duration.ofMillis(300));
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.concat(Flux.just(answer("first")), Flux.interval(Duration.ofMillis(20)).map(t -> answer("more"))));
        assertThatThrownBy(() -> route(settings, primary, fallback).stream(List.of(), List.of(), null).doOnNext(chunk -> count.incrementAndGet()).blockLast(Duration.ofSeconds(3)))
                .isInstanceOf(IllegalStateException.class).hasCause(null);
        assertThat(count.get()).isGreaterThan(1); verifyNoInteractions(fallback);
    }

    @Test void cancellingRecoveryProbeReleasesItsPermitAndTheNextRequestCanRestorePrimary() {
        var time = new java.util.concurrent.atomic.AtomicLong();
        var shared = new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5), time::get);
        shared.failure(shared.acquire(), ModelFailureClassifier.Failure.QUOTA);
        time.addAndGet(Duration.ofMinutes(5).toNanos());
        var primary = model(); var fallback = model();
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.never());
        var candidates = List.of(new ManagedAgentModel.Candidate("primary", primary, shared), new ManagedAgentModel.Candidate("backup", fallback, circuit()));
        var route = new ManagedAgentModel(candidates, null, new AgentModelProperties(), true);
        var subscription = route.stream(List.of(), List.of(), null).subscribe();
        assertThat(shared.health().state()).isEqualTo("HALF_OPEN");
        subscription.dispose();
        assertThat(shared.health().state()).isEqualTo("PROBE_READY");
        when(primary.stream(anyList(), anyList(), any())).thenReturn(Flux.just(answer("restored")));
        route.stream(List.of(), List.of(), null).blockLast();
        assertThat(shared.health().state()).isEqualTo("CLOSED"); verifyNoInteractions(fallback);
    }
}
