package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;

/** Original V44 digest algorithms shared by production and the admitted migration verifier. */
public final class ContextDigests {
    private ContextDigests() {}
    public static String bootstrapHash(ObjectMapper json,long owner,String session,String scope,String task,long through,String initial) {
        return hash(DurableContextProtocols.encode(json,List.of(owner,session,scope,task,through,initial)));
    }
    public static String summaryHash(ObjectMapper json,String summary,String messageState,String sources,String scope,
            long covered,String historyHash,String originalState) {
        return hash(DurableContextProtocols.encode(json,List.of(summary,messageState,sources,scope,covered,historyHash,originalState)));
    }
    public static String hash(String value){return DurableContextProtocols.hash(value);}
}
