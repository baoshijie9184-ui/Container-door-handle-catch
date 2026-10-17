package com.ruanzhu.doorhandle.module.ai.workbench;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("agentscope.workbench")
public class WorkbenchProperties {
    private boolean enabled;
    private boolean plans=true,questions=true,files=true,forks=true,children=true,jobs=true,usage=true,recovery=true;
    public boolean isEnabled(){return enabled;} public void setEnabled(boolean value){enabled=value;}
    public boolean isPlans(){return plans;} public void setPlans(boolean value){plans=value;}
    public boolean isQuestions(){return questions;} public void setQuestions(boolean value){questions=value;}
    public boolean isFiles(){return files;} public void setFiles(boolean value){files=value;}
    public boolean isForks(){return forks;} public void setForks(boolean value){forks=value;}
    public boolean isChildren(){return children;} public void setChildren(boolean value){children=value;}
    public boolean isJobs(){return jobs;} public void setJobs(boolean value){jobs=value;}
    public boolean isUsage(){return usage;} public void setUsage(boolean value){usage=value;}
    public boolean isRecovery(){return recovery;} public void setRecovery(boolean value){recovery=value;}
}
