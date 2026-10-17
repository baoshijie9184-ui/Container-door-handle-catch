package com.ruanzhu.doorhandle.module.device.api;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.mapper.*;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ResourceAgentAlertApiTest {
    final DeviceCaptureAlertMapper mapper=mock(DeviceCaptureAlertMapper.class);
    final DeviceMapper devices=mock(DeviceMapper.class);
    final ResourceAgentReadApiImpl api=new ResourceAgentReadApiImpl(devices,mapper);
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    @BeforeAll static void metadata(){TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(),"alert-test"),DeviceCaptureAlert.class);}
    DeviceCaptureAlert row(long id){
        var row=new DeviceCaptureAlert();row.setId(id);row.setAlertId("ALERT-CODE-"+id);row.setDeviceId(9L);row.setDeviceCode("LINE-A");
        row.setAlertType("CAPTURE_EXCEPTION");row.setAlertLevel("MAJOR");row.setStatus("OPEN");
        row.setAlertMessage("PRIVATE_FREE_TEXT");row.setRuntimeSnapshotJson("PRIVATE_OSS_KEY");row.setAckRemark("PRIVATE_REMARK");
        return row;
    }
    @Test void filteredKeysetQueryIsBoundedAndDoesNotFetchSnapshotOrNarrativeColumns(){
        when(mapper.selectList(any())).thenReturn(List.of(row(99),row(98),row(97)));
        var result=api.alerts(boss,new ResourceAgentReadApi.AlertQuery("OPEN","CRITICAL","9","100",2));
        assertThat(result.items()).extracting(ResourceAgentReadApi.AlertView::alertId).containsExactly("99","98");
        assertThat(result.hasMore()).isTrue();assertThat(result.nextCursor()).isEqualTo("98");assertThat(result.queriedAt()).isNotNull();
        @SuppressWarnings("unchecked") ArgumentCaptor<LambdaQueryWrapper<DeviceCaptureAlert>> query=ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(mapper).selectList(query.capture());var wrapper=query.getValue();
        assertThat(wrapper.getSqlSegment()).contains("status =", "alert_level =", "device_id =", "id <", "ORDER BY id DESC", "LIMIT 3").doesNotContain("OFFSET");
        assertThat(wrapper.getParamNameValuePairs().values()).containsExactlyInAnyOrder("OPEN","CRITICAL",9L,100L);
        assertThat(wrapper.getSqlSelect()).contains("id","alert_id","device_id","status").doesNotContain("alert_message","runtime_snapshot_json","ack_","resolved_");
        verifyNoInteractions(devices);
    }
    @Test void endOfListAndEmptyResultsDoNotInventCursorOrTotals(){
        when(mapper.selectList(any())).thenReturn(List.of(row(5))).thenReturn(List.of());
        var query=new ResourceAgentReadApi.AlertQuery(null,null,null,null,20);
        assertThat(query.status()).isEqualTo("OPEN");assertThat(query.level()).isEqualTo("ALL");
        var one=api.alerts(boss,query);assertThat(one.hasMore()).isFalse();assertThat(one.nextCursor()).isNull();
        assertThat(api.alerts(boss,query).items()).isEmpty();
    }
    @Test void detailReturnsCurrentStateAndSupportsOrphanedDeviceWithoutLeakingSensitiveFields() throws Exception {
        var row=row(Long.MAX_VALUE);row.setDeviceId(null);row.setStatus("RESOLVED");
        when(mapper.selectOne(any())).thenReturn(row);
        var view=api.alert(boss,Long.MAX_VALUE);
        assertThat(view.alertId()).isEqualTo("9223372036854775807");assertThat(view.deviceId()).isNull();assertThat(view.status()).isEqualTo("RESOLVED");
        assertThat(new ObjectMapper().writeValueAsString(view)).doesNotContain("PRIVATE_","runtimeSnapshot","alertMessage","ackRemark");
        when(mapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(()->api.alert(boss,1)).isInstanceOfSatisfying(BusinessException.class,e->assertThat(e.getCode()).isEqualTo(404));
    }
    @Test void inspectorsAndInvalidDetailIdsNeverReachStorage(){
        var staff=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.alerts(staff,new ResourceAgentReadApi.AlertQuery(null,null,null,null,20))).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.alert(staff,1)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.alert(boss,0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper,devices);
    }
    @Test void queryRejectsUnknownFiltersAndNonCanonicalOrOverflowingIds(){
        for(String id:List.of("0","01","-1","1.0","1e2","9223372036854775808","1 OR 1=1")) {
            assertThatThrownBy(()->new ResourceAgentReadApi.AlertQuery(null,null,id,null,20)).isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(()->new ResourceAgentReadApi.AlertQuery(null,null,null,id,20)).isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(()->new ResourceAgentReadApi.AlertQuery("open",null,null,null,20)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->new ResourceAgentReadApi.AlertQuery(null,"WARNING",null,null,20)).isInstanceOf(IllegalArgumentException.class);
        for(int size:new int[]{0,101})assertThatThrownBy(()->new ResourceAgentReadApi.AlertQuery(null,null,null,null,size)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper,devices);
    }
}
