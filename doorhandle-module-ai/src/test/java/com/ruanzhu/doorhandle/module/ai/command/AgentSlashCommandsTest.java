package com.ruanzhu.doorhandle.module.ai.command;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.evolution.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentSlashCommandsTest {
    final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    final SkillEvolutionService evolution=mock(SkillEvolutionService.class);
    final AgentJournal.Run run=mock(AgentJournal.Run.class);
    final AgentSlashCommands commands=new AgentSlashCommands(evolution);
    @Test void ordinaryInputAndHelpDoNotReadSkillsOrCallModels(){
        assertThat(commands.prepare(actor,"https://example.org/page",run)).isNull();
        assertThat(commands.prepare(actor,"/help",run).reply()).contains("/skills","/skill");verify(evolution).linksEnabled();verifyNoMoreInteractions(evolution);
    }
    @Test void unsupportedInstallAndUnknownSkillsNeverFallThroughToOrdinaryModelExecution(){
        assertThat(commands.prepare(actor,"/skills install https://example.org/package",run).reply()).contains("尚未启用");verify(evolution).linksEnabled();verifyNoMoreInteractions(evolution);
        when(run.id()).thenReturn("run-1");
        when(evolution.commandSkill(eq(actor),eq("unavailable"),eq(true),eq("run-1"),anyString())).thenThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND,"技能不可用"));
        assertThat(commands.prepare(actor,"/unavailable 执行脚本",run).reply()).contains("技能不可用");
        verify(run).event(eq("COMMAND_REJECTED"),argThat(p->Integer.valueOf(404).equals(p.get("status"))));
    }
    @Test void explicitSelectionReturnsQuestionSeparatelyAndDoesNotJournalContent(){
        when(run.id()).thenReturn("run-1");var metadata=new SkillDtos.AvailableSkill("skill-00000000-0000-0000-0000-000000000000","task-guide",1,"任务查询",List.of("get_task_detail"));
        var skill=new SkillDtos.LoadedSkill(metadata,"INSPECTOR","PRIVATE_GUIDANCE","a".repeat(64));
        when(evolution.commandSkill(eq(actor),eq("task-guide"),eq(true),eq("run-1"),anyString())).thenReturn(skill);
        var plan=commands.prepare(actor,"/skill task-guide 查询任务进度",run);
        assertThat(plan.reply()).isNull();assertThat(plan.skill()).isEqualTo(skill);assertThat(plan.question()).isEqualTo("查询任务进度");
        verify(run).event(eq("SKILL_COMMAND_LOADED"),argThat(p->p.get("skillId").equals(metadata.skillId())&&!p.toString().contains("PRIVATE_GUIDANCE")&&!p.toString().contains("查询任务进度")));
        assertThat(commands.prepare(actor,"/task-guide",run).reply()).contains("PRIVATE_GUIDANCE","已加载");
    }
    @Test void enabledLinkInstallOnlyReturnsConfirmationNavigationAndDoesNotDownloadOrLoad(){
        when(evolution.linksEnabled()).thenReturn(true);
        var plan=commands.prepare(actor,"/skills install https://github.com/anthropics/skills/tree/main/skills/skill-creator",run);
        assertThat(plan.reply()).contains("尚未下载","installUrl=","提交独立审核");assertThat(plan.skill()).isNull();
        assertThat(commands.prepare(actor,"/skills install https://127.0.0.1/private",run).reply()).contains("公开 GitHub");
        verify(evolution,times(2)).linksEnabled();verifyNoMoreInteractions(evolution);
    }
}
