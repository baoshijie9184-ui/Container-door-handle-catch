package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.*;
import io.agentscope.core.model.transport.HttpTransportException;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ModelAttemptTraceTest {
    record Event(String type, Map<String, Object> fields) {}
    private final List<Event> events = new CopyOnWriteArrayList<>();
    private final ModelAttemptTrace trace = new ModelAttemptTrace((type, fields) -> events.add(new Event(type, Map.copyOf(fields))));
    private Model model(String name) { var model=mock(Model.class);when(model.getModelName()).thenReturn(name);return model; }
    private ModelCircuit circuit() { return new ModelCircuit(2,Duration.ofSeconds(60),Duration.ofMinutes(5)); }
    private ChatResponse answer() { return ChatResponse.builder().content(List.of(TextBlock.builder().text("PRIVATE_REPLY").build())).build(); }
    private ManagedAgentModel route(Model primary, Model backup, ModelCircuit circuit) {
        return new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate("custom:primary","custom",primary,circuit),
                new ManagedAgentModel.Candidate("deepseek:backup","deepseek",backup,circuit())),null,new AgentModelProperties(),true);
    }
    private Flux<ChatResponse> observed(ManagedAgentModel route) {
        return route.stream(List.of(),List.of(),null).contextWrite(context->context.put(ModelAttemptTrace.CONTEXT_KEY,trace));
    }
    @Test void quotaFailureAndBackupSuccessRecordActualIdentityAndOnlyCodedFailureMetadata() {
        var primary=model("primary-name");var backup=model("backup-name");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.error(new HttpTransportException("PRIVATE_SECRET",402,"PRIVATE_ERROR_BODY")));
        when(backup.stream(anyList(),anyList(),any())).thenReturn(Flux.just(answer()));
        observed(route(primary,backup,circuit())).blockLast();
        assertThat(events).extracting(Event::type).containsExactly("MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_ERROR","MODEL_FALLBACK_SELECTED","MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_COMPLETED");
        assertThat(events.get(1).fields()).containsEntry("provider","custom").containsEntry("model","primary-name")
                .containsEntry("failureReason","QUOTA").containsEntry("httpStatus",402).containsKey("durationMs").doesNotContainKey("firstContentMs");
        assertThat(events.get(4).fields()).containsEntry("provider","deepseek").containsEntry("modelId","deepseek:backup")
                .containsEntry("model","backup-name").containsEntry("attempt",2).containsKeys("durationMs","firstContentMs");
        assertThat(events.toString()).doesNotContain("PRIVATE_SECRET","PRIVATE_ERROR_BODY","PRIVATE_REPLY");
    }
    @Test void providerUsageKeepsDistinctFailedAndBackupAttemptsAndUnknownDoesNotBecomeZero(){
        var primary=model("primary");var backup=model("backup");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.error(new HttpTransportException("private",402,"private")));
        var usage=new ChatUsage(41,7,0.01);when(backup.stream(anyList(),anyList(),any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("answer").build())).usage(usage).build()));
        var ids=new ArrayList<String>();var values=new ArrayList<Map<String,Object>>();var recorder=new ModelUsageTrace((id,data)->{ids.add(id);values.add(new LinkedHashMap<>(data));});
        route(primary,backup,circuit()).stream(List.of(),List.of(),null).contextWrite(context->context.put(ModelUsageTrace.CONTEXT_KEY,recorder)).blockLast();
        assertThat(ids).hasSize(2).doesNotHaveDuplicates();assertThat(values.get(0)).containsEntry("status","FAILED").containsEntry("inputTokens",null).containsEntry("basis","UNAVAILABLE");assertThat(values.get(1)).containsEntry("provider","deepseek").containsEntry("inputTokens",41).containsEntry("outputTokens",7).containsEntry("basis","PROVIDER_REPORTED");
    }
    @Test void coolingCandidateIsSkippedWithoutClaimingAnotherProviderRequest() {
        var primary=model("primary");var backup=model("backup");var shared=circuit();
        shared.failure(shared.acquire(),ModelFailureClassifier.Failure.QUOTA);
        when(backup.stream(anyList(),anyList(),any())).thenReturn(Flux.just(answer()));
        observed(route(primary,backup,shared)).blockLast();
        assertThat(events).extracting(Event::type).containsExactly("MODEL_CANDIDATE_SKIPPED","MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_COMPLETED");
        assertThat(events.get(0).fields()).containsEntry("failureReason","CIRCUIT_OPEN").containsEntry("attempt",1);
        verify(primary,never()).stream(anyList(),anyList(),any());
    }
    @Test void partialResponseFailureCannotReplayAndRetainsFirstContentTiming() {
        var primary=model("primary");var backup=model("backup");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.concat(Flux.just(answer()),Flux.error(new java.util.concurrent.TimeoutException("PRIVATE_ERROR"))));
        assertThatThrownBy(()->observed(route(primary,backup,circuit())).blockLast()).hasCause(null).hasMessageNotContaining("PRIVATE_ERROR");
        assertThat(events).extracting(Event::type).containsExactly("MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_ERROR");
        assertThat(events.get(1).fields()).containsEntry("failureReason","TIMEOUT").containsKey("firstContentMs");
        verify(backup,never()).stream(anyList(),anyList(),any());
    }
    @Test void cancelRecordsExactlyOneCandidateTerminalAndNeverUsesBackup() {
        var primary=model("primary");var backup=model("backup");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.never());
        var subscription=observed(route(primary,backup,circuit())).subscribe();subscription.dispose();subscription.dispose();
        assertThat(events).extracting(Event::type).containsExactly("MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_CANCELLED");
        verify(backup,never()).stream(anyList(),anyList(),any());
    }
    @Test void failedStartJournalPreventsNetworkAndDoesNotPoisonTheCircuit() {
        var primary=model("primary");var backup=model("backup");var shared=circuit();
        var broken=new ModelAttemptTrace((type,fields)->{throw new IllegalStateException("PRIVATE_DATABASE_ERROR");});
        assertThatThrownBy(()->route(primary,backup,shared).stream(List.of(),List.of(),null)
                .contextWrite(context->context.put(ModelAttemptTrace.CONTEXT_KEY,broken)).blockLast()).hasCause(null).hasMessageNotContaining("PRIVATE_DATABASE_ERROR");
        verify(primary,never()).stream(anyList(),anyList(),any());verify(backup,never()).stream(anyList(),anyList(),any());
        assertThat(shared.health().state()).isEqualTo("CLOSED");assertThat(shared.health().lastFailure()).isNull();
    }
    @Test void failedCompletionJournalCannotTriggerAnExtraPaidRequest() {
        var primary=model("primary");var backup=model("backup");var shared=circuit();
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.just(answer()));
        var broken=new ModelAttemptTrace((type,fields)->{if(type.equals("MODEL_ATTEMPT_COMPLETED"))throw new IllegalStateException("database");});
        assertThatThrownBy(()->route(primary,backup,shared).stream(List.of(),List.of(),null)
                .contextWrite(context->context.put(ModelAttemptTrace.CONTEXT_KEY,broken)).blockLast()).isInstanceOf(IllegalStateException.class);
        verify(backup,never()).stream(anyList(),anyList(),any());assertThat(shared.health().lastFailure()).isNull();
    }
    @Test void subscriberContextsStaySeparateEvenWhenTheSameRouterChangesThreads() {
        var primary=model("primary");var backup=model("backup");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Mono.delay(Duration.ofMillis(20)).map(t->answer()).flux());
        var other=new CopyOnWriteArrayList<Event>();var otherTrace=new ModelAttemptTrace((type,fields)->other.add(new Event(type,fields)));
        var route=route(primary,backup,circuit());
        Flux.merge(observed(route),route.stream(List.of(),List.of(),null).contextWrite(context->context.put(ModelAttemptTrace.CONTEXT_KEY,otherTrace))).blockLast();
        assertThat(events).extracting(Event::type).containsExactly("MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_COMPLETED");
        assertThat(other).extracting(Event::type).containsExactly("MODEL_ATTEMPT_STARTED","MODEL_ATTEMPT_COMPLETED");
    }
    @Test void emptyResponseProducesExplicitReasonBeforeBackup() {
        var primary=model("primary");var backup=model("backup");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.empty());
        when(backup.stream(anyList(),anyList(),any())).thenReturn(Flux.just(answer()));
        observed(route(primary,backup,circuit())).blockLast();
        assertThat(events.get(1).fields()).containsEntry("failureReason","EMPTY_RESPONSE");
    }
}
