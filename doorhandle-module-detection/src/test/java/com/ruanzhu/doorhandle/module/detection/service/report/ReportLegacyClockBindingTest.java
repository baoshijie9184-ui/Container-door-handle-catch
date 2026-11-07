package com.ruanzhu.doorhandle.module.detection.service.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Pure admission/type tests; real copy hashes and SQL fences are verified by ECS MySQL tests. */
class ReportLegacyClockBindingTest {
    private static final String EVENT="11111111-1111-1111-1111-111111111111",REPORT="qr-22222222-2222-2222-2222-222222222222";
    @Test void unresolvedEntryCannotBeginAClaimOrDeferTransaction(){
        var jdbc=mock(JdbcTemplate.class);var data=mock(DataSource.class);when(jdbc.getDataSource()).thenReturn(data);
        var repository=new ReportEventRepository(jdbc);clearInvocations(jdbc,data);
        var entry=new ReportEventRepository.Entry(EVENT,REPORT,"detection.report.submitted.v1","{}","PENDING",2,"retained-token",
                "UNRESOLVED",Map.of("created_at","2026-10-14 16:30:00"));
        assertThat(repository.claim(entry,LocalDateTime.of(2030,1,1,0,0),LocalDateTime.of(2030,1,1,1,0))).isNull();
        repository.defer(entry,LocalDateTime.of(2030,1,2,0,0));verifyNoInteractions(jdbc,data);
    }
    @Test void kafkaReplayOfAnUnresolvedOutboxCannotOpenAReceiptTransaction()throws Exception{
        var jdbc=mock(JdbcTemplate.class);var data=mock(DataSource.class);when(jdbc.getDataSource()).thenReturn(data);
        var repository=mock(ReportEventRepository.class);var json=new ObjectMapper();var codec=new ReportEventCodec(json);
        var event=new ReportLifecycleEvent(EVENT,REPORT,1,"SUBMITTED",2,1);String payload=json.writeValueAsString(event);
        when(repository.get(EVENT)).thenReturn(new ReportEventRepository.Entry(EVENT,REPORT,event.eventType(),payload,"DELIVERED",2,null,
                "UNRESOLVED",Map.of("delivered_at","2026-10-14 16:30:05")));
        var inbox=new ReportEventInbox(jdbc,repository,codec,new DataSourceTransactionManager(data));clearInvocations(jdbc,data);
        assertThatThrownBy(()->inbox.receive(REPORT,payload)).isInstanceOf(IllegalStateException.class).hasMessageContaining("历史报告事件时间需核对");
        assertThatThrownBy(()->inbox.receive("other-report",payload)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(jdbc,data);verify(repository).get(EVENT);
    }
    @Test void reportDtoRetainsSqlNullAndRawWallClockWithoutInventingDisplayTimes(){
        var times=new LinkedHashMap<String,String>();times.put("created_at","2026-10-14 16:30:00");times.put("delivered_at",null);
        var delivery=new QualityReportDtos.EventDelivery(EVENT,"detection.report.submitted.v1","PENDING",2,null,null,null,null,"UNRESOLVED",times);
        var audit=new QualityReportDtos.Audit(1,"fixture","SUBMIT","DRAFT","SUBMITTED",2,null,null,null,null,null,null,"UNRESOLVED",times);
        times.put("created_at","changed");
        assertThat(delivery.nextAttemptAt()).isNull();assertThat(delivery.deliveredAt()).isNull();assertThat(delivery.consumedAt()).isNull();assertThat(audit.createdAt()).isNull();
        assertThat(delivery.sourceWallTimes()).containsEntry("created_at","2026-10-14 16:30:00").containsEntry("delivered_at",null);
        assertThat(audit.sourceWallTimes()).isEqualTo(delivery.sourceWallTimes());
        assertThatThrownBy(()->delivery.sourceWallTimes().put("created_at","rewritten")).isInstanceOf(UnsupportedOperationException.class);
    }
}
