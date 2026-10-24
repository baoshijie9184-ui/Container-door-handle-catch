package com.ruanzhu.doorhandle.module.ai.context;

/** 每个主/子 Agent 的压缩预算；会话摘要持久化由独立 context-store 开关控制。 */
public class ContextCompactionSettings {
    private boolean enabled;
    private int triggerMessages=32,triggerTokens=24000,keepMessages=6,maxSummaryChars=6000,timeoutSeconds=12,maxPerRun=3;
    public void validate(){
        if(triggerMessages<4||triggerMessages>200||keepMessages<2||keepMessages>=triggerMessages
                ||triggerTokens<1024||triggerTokens>1000000||maxSummaryChars<256||maxSummaryChars>12000
                ||timeoutSeconds<1||timeoutSeconds>30||maxPerRun<1||maxPerRun>5)
            throw new IllegalArgumentException("上下文压缩配置超出范围");
    }
    public boolean isEnabled(){return enabled;} public void setEnabled(boolean value){enabled=value;}
    public int getTriggerMessages(){return triggerMessages;} public void setTriggerMessages(int value){triggerMessages=value;}
    public int getTriggerTokens(){return triggerTokens;} public void setTriggerTokens(int value){triggerTokens=value;}
    public int getKeepMessages(){return keepMessages;} public void setKeepMessages(int value){keepMessages=value;}
    public int getMaxSummaryChars(){return maxSummaryChars;} public void setMaxSummaryChars(int value){maxSummaryChars=value;}
    public int getTimeoutSeconds(){return timeoutSeconds;} public void setTimeoutSeconds(int value){timeoutSeconds=value;}
    public int getMaxPerRun(){return maxPerRun;} public void setMaxPerRun(int value){maxPerRun=value;}
}
