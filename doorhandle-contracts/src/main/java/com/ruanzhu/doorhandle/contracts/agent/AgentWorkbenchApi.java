package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Map;

/** Account-private workbench facade. SDK state and filesystem paths never cross this boundary. */
public interface AgentWorkbenchApi {
    record Item(String id,String kind,String status,long revision,Map<String,Object> data,String updatedAt) {}
    Map<String,Boolean> capabilities();
    List<Item> list(AgentActor actor,String sessionId);
    Item command(AgentActor actor,String sessionId,String itemId,long revision,String requestId,String action,Map<String,Object> input);
    default String waitingPhase(AgentActor actor,String sessionId){return null;}
    default void turnSaved(AgentActor actor,String sessionId,long messageId){}
    default void assertForkPoint(AgentActor actor,String sessionId,long messageId){}
    default void forked(AgentActor actor,String sourceSession,String targetSession,long messageId){}
    default boolean canDispatchInput(AgentActor actor,String sessionId,String inputId){return true;}
    default boolean permitsSpecialistWrite(AgentActor actor,String runId,String specialist){return false;}
}
