package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Map;

/** App owns chat history, file delivery and queue admission. AI only uses this typed local facade. */
public interface WorkbenchSessionApi {
    void assertOwned(AgentActor actor,String sessionId);
    void continueSession(AgentActor actor,String sessionId,String requestId,String content);
    String fork(AgentActor actor,String sessionId,long throughMessageId,String requestId);
    record File(String id,String name,String contentType,long bytes,String sha256,String folder) {}
    List<File> files(AgentActor actor,String sessionId);
    File createArtifact(AgentActor actor,String sessionId,String requestId,String name,String content);
    String readText(AgentActor actor,String sessionId,String fileId);
    default List<AgentBusinessFilesApi.Resource> businessFiles(AgentActor actor,String sessionId){return List.of();}
    default List<AgentBusinessFilesApi.Resource> attachBusinessFiles(AgentActor actor,String sessionId,String requestId,String kind,String resourceId){throw new UnsupportedOperationException();}
    default List<AgentWorkbenchApi.Item> externalJobs(AgentActor actor,String sessionId){return List.of();}
}
