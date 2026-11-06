package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;

/** Closed records; original nested JSON and SDK states stay byte-for-byte strings. */
public final class DurableContextProtocols {
    private DurableContextProtocols() {}
    public record ContextHeadV1(String legacySource) {}
    public record ContextBootstrapV1(String agentScope,String initialState,String initialSha256,String legacySource) {}
    public record ContextSummaryV1(int schemaVersion,String sessionId,String agentScope,long contextRevision,
            long coveredThrough,String historySha256,String messageState,String policyVersion,long beforeChars,
            long afterChars,String originalState,String createdAtSource,String sourceUtcOffset) {}
    public record OriginEvidenceV1(String sourcesJson,String sourcesSha256) {}
    public record OffloadEvidenceV1(String contentSha256,long byteLength,String sourcesJson,String sourcesSha256,
            String createdAtSource,String sourceUtcOffset,String lineageKind,String sourceOffloadId,
            String sourceSessionId,Long throughMessageId) {}
    public record ContextAuditV1(String agentScope,String createdAtSource,String sourceUtcOffset) {}

    public static ObjectMapper mapper(ObjectMapper application) {
        return application.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .disable(SerializationFeature.INDENT_OUTPUT)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    }
    /** The original V44 algorithm, also used by the migration proof runner. */
    public static String bootstrapHash(ObjectMapper json,long owner,String session,String scope,String task,long through,String initial) {
        return ContextDigests.bootstrapHash(json,owner,session,scope,task,through,initial);
    }
    /** This is the original seven-component digest, not a digest of the summary text alone. */
    public static String summaryHash(ObjectMapper json,String summary,String messageState,String sources,String scope,
            long covered,String historyHash,String originalState) {
        return ContextDigests.summaryHash(json,summary,messageState,sources,scope,covered,historyHash,originalState);
    }
    public static String hash(String text) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
    public static String encode(ObjectMapper json,Object value) {
        try{return json.writeValueAsString(value);}catch(Exception invalid){throw new IllegalArgumentException("上下文记录无法序列化",invalid);}
    }
    public static void text(String value,int maximum,String label) {
        if(value==null||value.codePointCount(0,value.length())>maximum)throw new IllegalArgumentException("上下文字段无效: "+label);
    }
    public static void sha(String value) {
        if(value==null||!value.matches("[a-fA-F0-9]{64}"))throw new IllegalArgumentException("上下文摘要无效");
    }
    public static boolean digest(String actual,String expected) {
        sha(actual);sha(expected);return actual.equalsIgnoreCase(expected);
    }
    public static void bootstrap(ContextBootstrapV1 body) {
        if(body==null||body.initialState()==null||body.legacySource()!=null&&!body.legacySource().equals("agent_context_bootstrap"))throw new IllegalArgumentException("上下文启动载荷无效");
        text(body.agentScope(),160,"scope");sha(body.initialSha256());
    }
    public static void summary(ContextSummaryV1 body) {
        if(body==null||body.schemaVersion()!=1||body.contextRevision()<0||body.coveredThrough()<0||body.beforeChars()<0||body.afterChars()<0
                ||body.messageState()==null||body.originalState()==null)throw new IllegalArgumentException("上下文摘要载荷无效");
        text(body.sessionId(),128,"session");text(body.agentScope(),160,"scope");text(body.policyVersion(),64,"policy");sha(body.historySha256());
        clock(body.createdAtSource(),body.sourceUtcOffset());
    }
    public static void offload(OffloadEvidenceV1 body) {
        if(body==null||body.byteLength()<0||body.sourcesJson()==null)throw new IllegalArgumentException("上下文卸载载荷无效");
        sha(body.contentSha256());sha(body.sourcesSha256());clock(body.createdAtSource(),body.sourceUtcOffset());
        if("FORK".equals(body.lineageKind())){
            text(body.sourceOffloadId(),36,"source offload");text(body.sourceSessionId(),128,"source session");
            if(body.throughMessageId()==null||body.throughMessageId()<0||body.createdAtSource()!=null)throw new IllegalArgumentException("上下文分支来源无效");
        }else if(SetHolder.NOT_FORK.contains(body.lineageKind())){
            if(body.sourceOffloadId()!=null||body.sourceSessionId()!=null||body.throughMessageId()!=null
                    ||("LEGACY".equals(body.lineageKind())!=(body.createdAtSource()!=null)))throw new IllegalArgumentException("上下文卸载来源无效");
        }else throw new IllegalArgumentException("上下文卸载来源类型无效");
    }
    private static final class SetHolder {private static final java.util.Set<String> NOT_FORK=java.util.Set.of("TOOL","LEGACY");}
    private static void clock(String source,String offset) {
        if(source==null&&offset==null)return;
        if(source==null||offset==null||!source.matches("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}")||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("上下文历史时刻无效");
        java.time.LocalDateTime.parse(source,java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss.SSSSSS").withResolverStyle(java.time.format.ResolverStyle.STRICT));
        java.time.ZoneOffset.of(offset);
    }
}
