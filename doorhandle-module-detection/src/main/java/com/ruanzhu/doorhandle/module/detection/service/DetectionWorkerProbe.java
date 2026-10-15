package com.ruanzhu.doorhandle.module.detection.service;

public interface DetectionWorkerProbe {
    boolean hasConsumer(String group, String topic) throws Exception;
}
