/*
 * Copyright 2024-2026 the original author or authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.agentscope.extensions.model.openaiofficial;

import com.openai.client.OpenAIClient;
import com.openai.core.http.StreamResponse;
import com.openai.models.responses.Response;
import com.openai.models.responses.ResponseCreateParams;
import com.openai.models.responses.ResponseInputItem;
import com.openai.models.responses.ResponseStreamEvent;
import io.agentscope.core.message.Msg;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.ExecutionConfig;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.model.ModelContextWindows;
import io.agentscope.core.model.ModelProviderSupport;
import io.agentscope.core.model.ModelUtils;
import io.agentscope.core.model.ToolSchema;
import io.agentscope.core.model.transport.ProxyConfig;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Flux;
import reactor.core.scheduler.Schedulers;

/**
 * AgentScope 2.0.4 Responses adapter with bounded, separate blocking I/O.
 *
 * <p>The original blocking SDK can outlive reactive cancellation before headers.
 * Reusing its shared boundedElastic worker can queue a healthy fallback behind
 * that call. Keep Responses requests on a separate fixed executor; the physical
 * threads remain bounded even when cancellation cannot interrupt the SDK read.
 * The SDK request timeout still bounds abandoned calls. Unknown provider usage
 * remains unknown. This does not retry the Agent or any business tool.
 *
 * <p>This compatibility bridge deliberately shares the SDK extension package to
 * reuse its package-private mapper, parser and assembler without copying them.
 * Source adapted from AgentScope Java 2.0.4 OpenAIResponsesChatModel (Apache-2.0).
 * Revalidate this bridge whenever the pinned AgentScope version changes.
 */
public final class OpenAIResponsesIoBridge extends OpenAIResponsesChatModel implements AutoCloseable {
    private static final Logger log = LoggerFactory.getLogger(OpenAIResponsesIoBridge.class);
    private final OpenAIClient client;
    private final GenerateOptions configuredOptions;
    private final String apiKey;
    private final String baseUrl;
    private final Boolean strictTools = false;
    private final Boolean strictJsonSchema = null;
    private final ResponsesMultiAgentFormatter formatter = null;
    private final java.util.concurrent.ThreadPoolExecutor requests;
    private final reactor.core.scheduler.Scheduler requestScheduler;

    private OpenAIResponsesIoBridge(OpenAIClient client, GenerateOptions options, String apiKey, String baseUrl) {
        super(client, options, apiKey, baseUrl, false, null, null);
        this.client=client; this.configuredOptions=options; this.apiKey=apiKey; this.baseUrl=baseUrl;
        requests=new java.util.concurrent.ThreadPoolExecutor(4,4,0,java.util.concurrent.TimeUnit.SECONDS,
                new java.util.concurrent.ArrayBlockingQueue<>(32), runnable->{
                    Thread thread=new Thread(runnable,"agent-responses-io");thread.setDaemon(true);return thread;
                },new java.util.concurrent.ThreadPoolExecutor.AbortPolicy());
        requestScheduler=Schedulers.fromExecutorService(requests);
        setContextWindowSize(ModelContextWindows.lookup(options.getModelName(),ModelContextWindows.OPENAI));
        applyNativeStructuredOutputDefaults();
    }

    public static OpenAIResponsesIoBridge create(String apiKey,String baseUrl,String model,
            ProxyConfig proxy,Map<String,String> headers,GenerateOptions policy) {
        GenerateOptions options=GenerateOptions.mergeOptions(GenerateOptions.builder().apiKey(apiKey)
                .baseUrl(baseUrl).modelName(model).stream(true).build(),policy);
        options=ModelUtils.ensureDefaultExecutionConfig(options);
        if(options.getExecutionConfig().getRetryOn()==null) {
            ExecutionConfig execution=ExecutionConfig.mergeConfigs(
                    ExecutionConfig.builder().retryOn(OpenAIResponsesChatModel.moduleRetryOn()).build(),options.getExecutionConfig());
            options=GenerateOptions.mergeOptions(GenerateOptions.builder().executionConfig(execution).build(),options);
        }
        OpenAIClient client=OpenAISdkClientFactory.createClient(apiKey,baseUrl,headers,
                options.getExecutionConfig().getTimeout(),proxy);
        return new OpenAIResponsesIoBridge(client,options,apiKey,baseUrl);
    }

    @Override public void close() {
        try { client.close(); } finally { requestScheduler.dispose(); requests.shutdownNow(); }
    }

    @Override
    protected Flux<ChatResponse> doStream(
            List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {
        return ModelUtils.applyTimeoutAndRetry(
                doStream0(messages, tools, options),
                options,
                configuredOptions,
                configuredOptions.getModelName(),
                OpenAIOfficialConstants.PROVIDER_ID);
    }

    private Flux<ChatResponse> doStream0(
            List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {

        GenerateOptions effectiveOptions = GenerateOptions.mergeOptions(options, configuredOptions);

        validateConnectionFields(effectiveOptions);

        boolean stream = effectiveOptions.getStream() != null ? effectiveOptions.getStream() : true;

        String modelName = effectiveOptions.getModelName();
        log.debug("OpenAI API call: model={}", modelName);

        Function<List<Msg>, List<ResponseInputItem>> historyMapper =
                formatter != null ? formatter::formatHistory : ResponsesRequestMapper::mapHistory;

        ResponseCreateParams params =
                ResponsesRequestMapper.map(
                        messages,
                        tools,
                        effectiveOptions,
                        strictTools,
                        strictJsonSchema,
                        historyMapper);

        if (stream) {
            return buildStreamingFlux(params, modelName);
        } else {
            return buildNonStreamingFlux(params, modelName);
        }
    }

    private Flux<ChatResponse> buildNonStreamingFlux(
            ResponseCreateParams params, String modelName) {
        return onRequestIo(
                        cancelled -> {
                            Instant start = Instant.now();
                            try {
                                Response response = client.responses().create(params);
                                if (cancelled.get()) return Flux.empty();
                                return Flux.just(
                                        ResponsesResponseParser.parse(response, modelName, start));
                            } catch (RuntimeException e) {
                                if (cancelled.get()) return Flux.empty();
                                return Flux.error(OpenAIErrorTranslator.translate(e, modelName));
                            }
                        });
    }

    private Flux<ChatResponse> buildStreamingFlux(ResponseCreateParams params, String modelName) {
        return onRequestIo(
                        cancelled -> {
                            Instant start = Instant.now();
                            StreamResponse<ResponseStreamEvent> streamResponse = null;
                            try {
                                streamResponse = client.responses().createStreaming(params);
                                if (cancelled.get()) {
                                    ResponsesStreamingAssembler.closeQuietly(streamResponse);
                                    return Flux.empty();
                                }
                                return ResponsesStreamingAssembler.assemble(
                                        streamResponse, modelName, start);
                            } catch (RuntimeException e) {
                                if (streamResponse != null) {
                                    ResponsesStreamingAssembler.closeQuietly(streamResponse);
                                }
                                if (cancelled.get()) return Flux.empty();
                                return Flux.error(OpenAIErrorTranslator.translate(e, modelName));
                            }
                        });
    }

    private Flux<ChatResponse> onRequestIo(Function<java.util.concurrent.atomic.AtomicBoolean,Flux<ChatResponse>> request) {
        return Flux.defer(()->{
            var cancelled=new java.util.concurrent.atomic.AtomicBoolean();
            // Register before scheduling. A cancelled pre-header call may finish
            // later; close its stream and discard its late signals locally.
            return Flux.defer(()->request.apply(cancelled)).subscribeOn(requestScheduler)
                    .doOnCancel(()->cancelled.set(true));
        });
    }

    private void validateConnectionFields(GenerateOptions effectiveOptions) {
        String effectiveApiKey = ModelProviderSupport.trimToNull(effectiveOptions.getApiKey());
        if (effectiveApiKey != null && !Objects.equals(effectiveApiKey, apiKey)) {
            throw new OpenAIOfficialModelException(
                    "apiKey override per request is not supported by the openai-official"
                            + " provider. The apiKey must match the one configured at model"
                            + " construction.",
                    effectiveOptions.getModelName());
        }

        String effectiveBaseUrl = ModelProviderSupport.trimToNull(effectiveOptions.getBaseUrl());
        if (effectiveBaseUrl != null && !Objects.equals(effectiveBaseUrl, baseUrl)) {
            throw new OpenAIOfficialModelException(
                    "baseUrl override per request is not supported by the openai-official"
                            + " provider. The baseUrl must match the one configured at model"
                            + " construction.",
                    effectiveOptions.getModelName());
        }
    }

}
