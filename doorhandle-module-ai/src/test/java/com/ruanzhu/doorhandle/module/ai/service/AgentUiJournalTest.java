package com.ruanzhu.doorhandle.module.ai.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentConversationApi;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentUiJournalTest {
    @Test void forwardsActualToolReceiptsWithStableIdsWithoutArgumentsOrReasoning(){
        var stored=mock(AgentJournal.Run.class);var events=new ArrayList<AgentConversationApi.Event>();
        var run=AgentScopeConversationService.uiJournal(stored,events::add);
        var fields=Map.<String,Object>of("agent","task-reader","tool","get_task_detail","callId","call-1","elapsedMs",17,"arguments","SECRET_ARGUMENTS");
        run.event("TOOL_STARTED",fields);run.event("MODEL_STARTED",fields);run.event("TOOL_COMPLETED",fields);
        assertThat(events).hasSize(2);assertThat(events.get(0).callId()).isEqualTo("call-1");assertThat(events.get(1).type()).isEqualTo("TOOL_COMPLETED");
        assertThat(events.toString()).doesNotContain("SECRET_ARGUMENTS");verify(stored).event("MODEL_STARTED",fields);
    }
}
