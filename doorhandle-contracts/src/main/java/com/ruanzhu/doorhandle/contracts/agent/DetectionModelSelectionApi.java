package com.ruanzhu.doorhandle.contracts.agent;

/** Published detection model selection, separate from LLM configuration and model administration. */
public interface DetectionModelSelectionApi {
    record Model(int id,String name,String version,String revision) {}
    Model select(Integer modelId);
    void recordUse(Model expected);
}
