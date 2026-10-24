package com.ruanzhu.doorhandle.contracts.agent;

/** Non-secret revision snapshot shared by queue admission, execution and memory HTTP orchestration. */
public interface ModelConfigurationApi {
    record Active(long version,String defaultModel,String memoryModel){}
    Active active();
    default void assertMemoryAvailable() {}
    default void assertTaskConfiguration(long revision,String modelId) {}
}
