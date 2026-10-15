package com.ruanzhu.doorhandle.module.detection.service.report;

@FunctionalInterface
public interface ReportEventTransport {
    void send(String reportId,String payload)throws Exception;
}
