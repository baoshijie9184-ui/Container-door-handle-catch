package com.ruanzhu.doorhandle.contracts.agent;

/** 仅供服务端知识检索重写/重排，统一经 AgentScope 调用受管理的模型。 */
public interface AgentTextApi {
    String generate(String systemPrompt, String input);
}
