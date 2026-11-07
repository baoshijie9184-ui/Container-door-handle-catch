package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Map;

/** App owns chat history, file delivery and queue admission. AI only uses this typed local facade. */
public interface WorkbenchSessionApi {
    void assertOwned(AgentActor actor,String sessionId);
    void continueSession(AgentActor actor,String sessionId,String requestId,String content);
    String fork(AgentActor actor,String sessionId,long throughMessageId,String requestId);
    /** clockStatus describes retained historical provenance, not the time of a new user operation. */
    record File(String id,String name,String contentType,long bytes,String sha256,String folder,
                String clockStatus,Map<String,String> sourceWallTimes) {
        public File(String id,String name,String contentType,long bytes,String sha256,String folder){this(id,name,contentType,bytes,sha256,folder,"UTC",Map.of());}
        public File { clockStatus=clockStatus==null?"UTC":clockStatus;sourceWallTimes=sourceWallTimes==null?Map.of():java.util.Collections.unmodifiableMap(new java.util.LinkedHashMap<>(sourceWallTimes)); }
    }
    List<File> files(AgentActor actor,String sessionId);
    File createArtifact(AgentActor actor,String sessionId,String requestId,String name,String content);
    String readText(AgentActor actor,String sessionId,String fileId);
    default List<AgentBusinessFilesApi.Resource> businessFiles(AgentActor actor,String sessionId){return List.of();}
    default List<AgentBusinessFilesApi.Resource> attachBusinessFiles(AgentActor actor,String sessionId,String requestId,String kind,String resourceId){throw new UnsupportedOperationException();}
    default List<AgentWorkbenchApi.Item> externalJobs(AgentActor actor,String sessionId){return List.of();}
}
