package com.ruanzhu.doorhandle.module.ai.model;

import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Pure request construction checks; executed only by the ECS verification entrypoint. */
class ModelTokenReservationTest {
    @Test void officialProviderRejectsUnsupportedOptionsBeforeAnyQuotaAdmission() {
        assertThatThrownBy(()->io.agentscope.extensions.model.openaiofficial.OpenAIResponsesIoBridge.validateBudgetRequest(
                List.of(new UserMessage("hello")),List.of(),GenerateOptions.builder().thinkingBudget(10).build(),"gpt-fixture"))
                .isInstanceOf(RuntimeException.class);
    }
    @Test void includesToolSchemasAndUtf8TextWithoutCallingTheProvider() {
        Model model=mock(Model.class);
        var empty=ModelTokenReservation.prepare(List.of(),List.of(),null,100,model);
        var tools=List.of(ToolSchema.builder().name("inspect").description("读取检测任务")
                .parameters(Map.of("type","object","properties",Map.of("batch",Map.of("type","string")))).build());
        var request=ModelTokenReservation.prepare(List.of(new UserMessage("检查集装箱")),tools,null,100,model);
        assertThat(request.tokens()).isGreaterThan(empty.tokens());
        assertThat(request.basis()).isEqualTo("TEXT_UTF8_ESTIMATE_V1");
        verifyNoInteractions(model);
    }
    @Test void enforcesOutputCeilingsAndOneSdkAttemptWhilePreservingStreamMode() {
        var options=GenerateOptions.builder().maxTokens(500).maxCompletionTokens(80).stream(false)
                .executionConfig(ExecutionConfig.builder().maxAttempts(5).build()).build();
        var plan=ModelTokenReservation.prepare(List.of(),List.of(),options,100,mock(Model.class));
        assertThat(plan.options().getMaxTokens()).isEqualTo(80);
        assertThat(plan.options().getMaxCompletionTokens()).isEqualTo(80);
        assertThat(plan.options().getExecutionConfig().getMaxAttempts()).isEqualTo(1);
        assertThat(plan.options().getStream()).isFalse();
    }
    @Test void storedProviderHistoryAndExtraOutputMultipliersCannotBypassTheEstimate() {
        for(String key:List.of("previous_response_id","conversation","prompt","n","max_output_tokens"))
            assertThatThrownBy(()->ModelTokenReservation.prepare(List.of(),List.of(),
                    GenerateOptions.builder().additionalBodyParam(key,"external-reference").build(),100,mock(Model.class)))
                    .isInstanceOf(IllegalArgumentException.class);
    }
    @Test void perRequestCredentialAndRouteOverridesAreRejectedBeforeAdmission() {
        var options=List.of(GenerateOptions.builder().apiKey("untrusted").build(),
                GenerateOptions.builder().modelName("another-model").build(),
                GenerateOptions.builder().additionalHeader("Authorization","untrusted").build(),
                GenerateOptions.builder().additionalQueryParam("api_key","untrusted").build());
        for(var option:options)assertThatThrownBy(()->ModelTokenReservation.prepare(List.of(),List.of(),option,100,mock(Model.class)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
