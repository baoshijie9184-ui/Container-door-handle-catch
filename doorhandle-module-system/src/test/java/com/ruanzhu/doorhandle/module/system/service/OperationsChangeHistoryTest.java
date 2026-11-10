package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** ECS-only field authorization and operation-time identity checks against persisted V1/V2 rows. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class OperationsChangeHistoryTest {
    OperationsMySqlFixture fixture;JdbcTemplate jdbc;TransactionTemplate tx;OperationsAuditService service;BusinessUserDirectory users;
    final AgentActor actor=new AgentActor(1,"original",AgentActor.Role.SUPERVISOR),reader=new AgentActor(2,"reader",AgentActor.Role.SUPERVISOR);
    final AtomicBoolean mayRead=new AtomicBoolean(true);
    final OperationsAuditService.Filter noFilter=new OperationsAuditService.Filter(null,null,null,null,null,null,null,null);
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.dataSource()));
        users=mock(BusinessUserDirectory.class);for(var who:List.of(actor,reader))when(users.current(who.userId(),who.username())).thenReturn(new BusinessUserDirectory.Identity(who.userId(),who.username(),true));
        service=new OperationsAuditService(jdbc,users);ReflectionTestUtils.setField(service,"changeHistoryEnabled",true);
        service.collaboration(List.of((who,scope,domain,type,id)->mayRead.get()&&"DEVICE".equals(domain)&&"DEVICE".equals(type)),event->{},null,null);
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}
    private void append(){tx.executeWithoutResult(status->service.appendChange(new OperationsAuditApi.ChangeEvent(
            new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","41","change-one","APPLIED",6L),"DEVICE","Original Name",5L,
            List.of(new ChangeHistory.Change("status","状态","REPLACE","IDLE","IN_USE","SCALAR",false)))));}
    @Test void supervisorCanReadOtherActorsLegacyEnterpriseMetadataWithoutInventingDiffs(){
        tx.executeWithoutResult(status->service.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","OLD_WRITE","41","legacy-other","APPLIED",-7L)));
        var page=service.changes(reader,Long.MAX_VALUE,50,noFilter);assertThat(page.items()).hasSize(1);
        var item=page.items().get(0);assertThat(item.actor().role()).isNull();assertThat(item.resourceType()).isNull();assertThat(item.diffAvailable()).isFalse();
        var detail=service.change(reader,item.id());assertThat(detail.diffAvailable()).isFalse();assertThat(detail.changes()).isEmpty();
        assertThat(detail.beforeVersion()).isNull();assertThat(detail.afterVersion()).isNull();
    }
    @Test void actorSnapshotSurvivesLaterDemotionAndAccountDisappearance(){
        append();when(users.current(actor.userId(),actor.username())).thenThrow(new SecurityException("old actor no longer exists"));
        var item=service.changes(reader,Long.MAX_VALUE,50,noFilter).items().get(0);
        assertThat(item.actor()).isEqualTo(new ChangeHistory.Actor("1","original","Original Name","SUPERVISOR"));
        assertThat(item.beforeVersion()).isEqualTo("5");assertThat(item.afterVersion()).isEqualTo("6");assertThat(item.resourceId()).isEqualTo("41");
        assertThat(service.change(reader,item.id()).changes()).singleElement().satisfies(change->assertThat(change.after()).isEqualTo("IN_USE"));
    }
    @Test void currentResourceRevocationDeniesDetailAndOtherActorsMetadata(){
        append();String id=service.changes(reader,Long.MAX_VALUE,50,noFilter).items().get(0).id();mayRead.set(false);
        assertThat(service.changes(reader,Long.MAX_VALUE,50,noFilter).items()).isEmpty();
        assertThatThrownBy(()->service.change(reader,id)).isInstanceOf(SecurityException.class);
        assertThat(service.changes(actor,Long.MAX_VALUE,50,noFilter).items()).singleElement().satisfies(item->{
            assertThat(item.resourceId()).isNull();assertThat(item.resourceType()).isNull();assertThat(item.diffAvailable()).isFalse();
        });
    }
    @Test void oldAuditKeepsLegacyResponseAndDoesNotInventADiffOrRole(){
        tx.executeWithoutResult(status->service.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","legacy","old-request","APPLIED",-7L)));
        assertThat(service.list(actor,Long.MAX_VALUE,50,null)).singleElement().satisfies(item->assertThat(item.get("resource_version")).isEqualTo(-7L));
        assertThat(service.changes(actor,Long.MAX_VALUE,50,noFilter).items()).singleElement().satisfies(item->{
            assertThat(item.actor().role()).isNull();assertThat(item.actor().username()).isNull();assertThat(item.diffAvailable()).isFalse();
        });
    }
    @Test void filtersAndPaginationRemainIntersectionsWithResourcePermission(){
        append();var onlyOther=new OperationsAuditService.Filter("DEVICE","DEVICE","41","999","SUPERVISOR","UPDATE",null,null);
        assertThat(service.changes(reader,Long.MAX_VALUE,1,onlyOther).items()).isEmpty();
        var first=service.changes(reader,Long.MAX_VALUE,1,noFilter);assertThat(first.items()).hasSize(1);
        assertThat(service.changes(reader,Long.parseLong(first.nextCursor()),1,noFilter).items()).isEmpty();
    }
    @Test void numericV2ValuesRoundTripWithoutLosingTypesOrConflictingWithExactDuplicate() throws Exception {
        var first=List.of(new ChangeHistory.Change("count","数量","REPLACE",1,new java.math.BigDecimal("2.5000"),"NUMBER",false),
                new ChangeHistory.Change("enabled","开关","REPLACE",false,"false","SCALAR",false),
                new ChangeHistory.Change("optional","可选值","REPLACE",null,"null","SCALAR",false),
                new ChangeHistory.Change("ownerUserId","人员编号","REPLACE","9007199254740993","9007199254740994","ID",false),
                new ChangeHistory.Change("precision","精确数值","REPLACE",new java.math.BigDecimal("0.1234567890123456789012345"),new java.math.BigDecimal("0.2"),"NUMBER",false));
        var metadata=new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","41","typed-numeric-change","APPLIED",6L);
        tx.executeWithoutResult(status->service.appendChange(new OperationsAuditApi.ChangeEvent(metadata,"DEVICE","Original Name",5L,first)));
        var stored=new com.fasterxml.jackson.databind.ObjectMapper().readTree(jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS'",String.class));
        assertThat(stored.path("changes").get(0).path("before").isNumber()).isTrue();assertThat(stored.path("changes").get(0).path("after").isNumber()).isTrue();
        assertThat(stored.path("changes").get(1).path("before").isBoolean()).isTrue();assertThat(stored.path("changes").get(1).path("after").isTextual()).isTrue();
        assertThat(stored.path("changes").get(2).path("before").isNull()).isTrue();assertThat(stored.path("changes").get(2).path("after").isTextual()).isTrue();
        assertThat(stored.path("changes").get(3).path("before").asText()).isEqualTo("9007199254740993");
        var item=service.changes(reader,Long.MAX_VALUE,50,noFilter).items().get(0);assertThat(service.change(reader,item.id()).changes()).isEqualTo(first);
        var replay=new ArrayList<>(first);replay.set(0,new ChangeHistory.Change("count","数量","REPLACE",1L,2.5,"NUMBER",false));
        tx.executeWithoutResult(status->service.appendChange(new OperationsAuditApi.ChangeEvent(metadata,"DEVICE","Original Name",5L,replay)));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Long.class)).isEqualTo(1);
        assertThat(service.changes(reader,Long.MAX_VALUE,50,noFilter).items()).singleElement().satisfies(again->assertThat(again.eventId()).isEqualTo(item.eventId()));
    }
}
