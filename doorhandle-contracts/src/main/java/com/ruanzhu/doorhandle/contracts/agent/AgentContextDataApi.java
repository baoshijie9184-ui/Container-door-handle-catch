package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

/** App owns canonical chat history and private context files. No SDK state or filesystem paths cross this boundary. */
public interface AgentContextDataApi {
    record Source(String kind,String resourceId,String version) {}
    record Message(long id,String role,String text,List<Source> sources) {}
    record History(long throughId,List<Message> messages,boolean hasMore) {}
    History history(AgentActor actor,String session,long afterId,long throughId,int limit);
    String historyDigest(AgentActor actor,String session,long throughId);
    void authorize(AgentActor actor,String session,List<Source> sources);
    default List<Source> pin(AgentActor actor,String session,List<Source> sources){authorize(actor,session,sources);return List.copyOf(sources);}
    WorkbenchSessionApi.File saveContextFile(AgentActor actor,String session,String requestId,String text);
    record Slice(String text,int offset,int nextOffset,boolean end,String sha256) {}
    Slice readContextFile(AgentActor actor,String session,String fileId,String expectedSha256,int offset,int limit);
    record ForkMessage(long sourceId,long targetId) {}
    List<ForkMessage> forkMessages(AgentActor actor,String source,String target,long throughId);
}
