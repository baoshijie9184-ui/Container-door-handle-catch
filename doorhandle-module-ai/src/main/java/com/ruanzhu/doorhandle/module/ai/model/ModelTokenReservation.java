package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import java.util.*;

/** Admission estimate only. The ledger always settles the complete provider report, including overruns. */
final class ModelTokenReservation {
    record Plan(long tokens, String basis, GenerateOptions options) { }
    private static final ObjectMapper JSON=new ObjectMapper();
    private static final Set<String> OVERRIDES=Set.of("model","messages","input","tools","max_tokens",
            "max_completion_tokens","max_output_tokens","thinking_budget","n",
            "previous_response_id","conversation","prompt","cached_content");
    private ModelTokenReservation() { }

    static Plan prepare(List<Msg> messages,List<ToolSchema> tools,GenerateOptions options,int serverMaxOutput,Model model) {
        if(serverMaxOutput<=0)throw new IllegalArgumentException("缺少模型输出上限");
        if(options==null)options=GenerateOptions.builder().build();
        if(options.getApiKey()!=null||options.getBaseUrl()!=null||options.getEndpointPath()!=null||options.getModelName()!=null)
            throw new IllegalArgumentException("额度调用不能覆盖已登记的模型连接");
        if(options.getAdditionalHeaders()!=null&&!options.getAdditionalHeaders().isEmpty()
                ||options.getAdditionalQueryParams()!=null&&!options.getAdditionalQueryParams().isEmpty())
            throw new IllegalArgumentException("额度调用不能覆盖已登记的鉴权或路由参数");
        if(options.getAdditionalBodyParams()!=null&&options.getAdditionalBodyParams().keySet().stream()
                .anyMatch(key->OVERRIDES.contains(key.toLowerCase(Locale.ROOT))))
            throw new IllegalArgumentException("额度调用参数不能覆盖计量边界");
        int output=serverMaxOutput;
        if(options.getMaxTokens()!=null)output=Math.min(output,positive(options.getMaxTokens()));
        if(options.getMaxCompletionTokens()!=null)output=Math.min(output,positive(options.getMaxCompletionTokens()));
        Integer thinking=options.getThinkingBudget();
        if(thinking!=null&&thinking<0)throw new IllegalArgumentException("思考额度必须明确且非负");
        var forced=GenerateOptions.builder().maxTokens(output)
                .executionConfig(ExecutionConfig.mergeConfigs(ExecutionConfig.builder().maxAttempts(1).build(),options.getExecutionConfig()));
        if(options.getMaxCompletionTokens()!=null)forced.maxCompletionTokens(output);
        if(thinking!=null)forced.thinkingBudget(Math.min(thinking,output));
        // AgentScope 2.0.4 gives the first argument precedence; other server-owned options are retained.
        GenerateOptions enforced=GenerateOptions.mergeOptions(forced.build(),options);
        long estimate=256; boolean textOnly=true;
        if(messages!=null)for(var message:messages) {
            if(message==null)throw new IllegalArgumentException("Invalid model message");
            var fields=new LinkedHashMap<String,Object>();
            fields.put("role",message.getRole());fields.put("name",message.getName());fields.put("content",message.getContent());
            estimate=Math.addExact(estimate,Math.addExact(64,bytes(fields)));
            textOnly&=textOnly(message.getContent());
        }
        if(tools!=null)estimate=Math.addExact(estimate,Math.addExact(bytes(tools),Math.multiplyExact(64L,tools.size())));
        if(options.getResponseFormat()!=null)estimate=Math.addExact(estimate,bytes(options.getResponseFormat()));
        if(options.getAdditionalBodyParams()!=null)estimate=Math.addExact(estimate,bytes(options.getAdditionalBodyParams()));
        String basis="TEXT_UTF8_ESTIMATE_V1";
        if(!textOnly) {
            // URL length cannot estimate image/audio/video tokenization. Never pretend a remote object is free.
            int window=model.getContextWindowSize();
            if(window<=0)throw new IllegalArgumentException("该多模态模型尚未登记可用于额度预留的上下文窗口");
            estimate=Math.max(estimate,window);basis="MODEL_CONTEXT_ESTIMATE_V1";
        }
        estimate=Math.addExact(estimate,output);
        if(thinking!=null)estimate=Math.addExact(estimate,Math.min(thinking,output));
        return new Plan(estimate,basis,enforced);
    }
    private static int positive(int value) {
        if(value<=0)throw new IllegalArgumentException("模型输出额度必须大于零");return value;
    }
    private static long bytes(Object value) {
        try{return JSON.writeValueAsBytes(value).length;}
        catch(Exception error){throw new IllegalArgumentException("无法计算本次调用的预留估算",error);}
    }
    private static boolean textOnly(List<ContentBlock> blocks) {
        if(blocks==null)return true;
        for(var block:blocks) {
            if(block instanceof ToolResultBlock result) { if(!textOnly(result.getOutput()))return false; }
            else if(!(block instanceof TextBlock||block instanceof ThinkingBlock||block instanceof ToolUseBlock))return false;
        }
        return true;
    }
}
