package com.ruanzhu.doorhandle.contracts.detection;

import java.util.Set;

/** 报告事件只携带资源引用和版本，不传输私人正文或检测文件地址。 */
public record ReportLifecycleEvent(String eventId,String reportId,long actorUserId,String status,int version,int schemaVersion) {
    public ReportLifecycleEvent {
        if(eventId==null||!eventId.matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
                ||reportId==null||!reportId.matches("qr-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
                ||actorUserId<1||version<2||schemaVersion!=1||status==null
                ||!Set.of("SUBMITTED","WITHDRAWN","APPROVED","REJECTED").contains(status))
            throw new IllegalArgumentException("Invalid report lifecycle event");
    }
    public String eventType(){return "detection.report."+status.toLowerCase(java.util.Locale.ROOT)+".v1";}
}
