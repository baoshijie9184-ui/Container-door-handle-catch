package com.ruanzhu.doorhandle.module.detection.service.report;

import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** 回执和只读事件状态同事务更新；消费不触发审批、任务放行或外部通知。 */
@Service
public class ReportEventInbox {
    private final JdbcTemplate jdbc;private final ReportEventRepository outbox;private final ReportEventCodec codec;private final TransactionTemplate tx;
    public ReportEventInbox(JdbcTemplate jdbc,ReportEventRepository outbox,ReportEventCodec codec,PlatformTransactionManager manager){
        this.jdbc=jdbc;this.outbox=outbox;this.codec=codec;this.tx=new TransactionTemplate(manager);
    }
    public boolean receive(String key,String payload){
        var event=codec.decode(payload);
        if(!event.reportId().equals(key))throw new IllegalArgumentException("Invalid report event key");
        var original=outbox.get(event.eventId());
        if(original==null||!event.reportId().equals(original.reportId())||!event.eventType().equals(original.eventType())||!event.equals(codec.decode(original.payload())))
            throw new IllegalArgumentException("Report event is not bound to committed outbox");
        String digest=codec.digest(event);
        return Boolean.TRUE.equals(tx.execute(status->{
            int inserted=jdbc.update("INSERT IGNORE INTO detection_report_event_receipt(event_id,report_id,event_type,report_version,payload_sha256,consumed_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",event.eventId(),event.reportId(),event.eventType(),event.version(),digest);
            var receipt=jdbc.queryForList("SELECT payload_sha256 FROM detection_report_event_receipt WHERE event_id=?",event.eventId());
            if(receipt.size()!=1||!digest.equals(receipt.get(0).get("payload_sha256")))throw new IllegalStateException("Report event receipt conflict");
            if(inserted==0)return false;
            jdbc.update("INSERT IGNORE INTO detection_report_event_state(report_id,last_version,status,last_event_id,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",event.reportId(),event.version(),event.status(),event.eventId());
            jdbc.update("UPDATE detection_report_event_state SET last_version=?,status=?,last_event_id=?,updated_at=CURRENT_TIMESTAMP WHERE report_id=? AND last_version<?",event.version(),event.status(),event.eventId(),event.reportId(),event.version());
            return true;
        }));
    }
}
