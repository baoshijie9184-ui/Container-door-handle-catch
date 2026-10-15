package com.ruanzhu.doorhandle.module.ai.evolution;

import io.agentscope.core.skill.AgentSkill;
import io.agentscope.core.skill.repository.*;
import java.util.List;

/** 发布版本的单轮只读快照；不写 SDK 工作区或修改技能文件。 */
public final class SkillSnapshotRepository implements AgentSkillRepository {
    private final List<AgentSkill> skills;
    public SkillSnapshotRepository(List<AgentSkill> skills){this.skills=List.copyOf(skills);}
    public AgentSkill getSkill(String name){return skills.stream().filter(s->s.getName().equals(name)).findFirst().orElse(null);}
    public List<String> getAllSkillNames(){return skills.stream().map(AgentSkill::getName).toList();}
    public List<AgentSkill> getAllSkills(){return skills;}
    public boolean skillExists(String name){return getSkill(name)!=null;}
    public boolean save(List<AgentSkill> values,boolean overwrite){throw new SecurityException("运行时技能仓库只读");}
    public boolean delete(String name){throw new SecurityException("运行时技能仓库只读");}
    public void setWriteable(boolean enabled){if(enabled)throw new SecurityException("运行时技能仓库只读");}
    public boolean isWriteable(){return false;}
    public AgentSkillRepositoryInfo getRepositoryInfo(){return new AgentSkillRepositoryInfo("approved-snapshot","project-mysql",false);}
    public String getSource(){return "approved-project";}
}
