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
    private void inspectorReader(){when(users.current(reader.userId(),reader.username())).thenReturn(new BusinessUserDirectory.Identity(reader.userId(),reader.username(),false));}
    private OperationsAuditService.Filter deviceHistory(){return new OperationsAuditService.Filter("DEVICE","DEVICE","41",null,null,null,null,null);}
    private void appendFor(AgentActor who,String scope,String resource,String request){
        tx.executeWithoutResult(status->service.appendChange(new OperationsAuditApi.ChangeEvent(
                new OperationsAuditApi.Event(who,scope,"DEVICE","UPDATE",resource,request,"APPLIED",1L),"DEVICE","Captured Name",0L,
                List.of(new ChangeHistory.Change("status","状态","REPLACE","IDLE","IN_USE","SCALAR",false)))));
    }
    @Test void inspectorGeneralHistoryIsPersonalEvenWhenOtherEnterpriseResourcesAreReadable(){
        append();inspectorReader();appendFor(new AgentActor(2,"reader",AgentActor.Role.INSPECTOR),"ENTERPRISE","42","my-change");
        assertThat(service.changes(reader,Long.MAX_VALUE,50,noFilter).items()).singleElement().satisfies(item->assertThat(item.actor().userId()).isEqualTo("2"));
        var forgedOther=new OperationsAuditService.Filter("DEVICE",null,null,"1",null,null,null,null);
        assertThat(service.changes(reader,Long.MAX_VALUE,50,forgedOther).items()).isEmpty();
    }
    @Test void inspectorExplicitResourceHistoryCanIncludeAnotherActorAfterCurrentAuthorization(){
        append();inspectorReader();
        assertThat(service.changes(reader,Long.MAX_VALUE,50,deviceHistory()).items()).singleElement().satisfies(item->{
            assertThat(item.actor().userId()).isEqualTo("1");assertThat(item.resourceId()).isEqualTo("41");assertThat(item.diffAvailable()).isTrue();
        });
        assertThatThrownBy(()->service.changes(reader,Long.MAX_VALUE,50,new OperationsAuditService.Filter("DEVICE","DEVICE",null,null,null,null,null,null))).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void inspectorResourcePermissionRevocationRemovesOthersHistoryAndDeniesItsDetail(){
        append();inspectorReader();String id=service.changes(reader,Long.MAX_VALUE,50,deviceHistory()).items().get(0).id();mayRead.set(false);
        assertThat(service.changes(reader,Long.MAX_VALUE,50,deviceHistory()).items()).isEmpty();
        assertThatThrownBy(()->service.change(reader,id)).isInstanceOf(SecurityException.class);
    }
    @Test void explicitResourceFilterNeverExposesAnotherActorsPrivateHistory(){
        append();appendFor(actor,"PRIVATE","41","other-private");inspectorReader();appendFor(new AgentActor(2,"reader",AgentActor.Role.INSPECTOR),"PRIVATE","41","my-private");
        assertThat(service.changes(reader,Long.MAX_VALUE,50,deviceHistory()).items()).extracting(ChangeHistory.Item::requestId).containsExactlyInAnyOrder("change-one","my-private");
        assertThat(service.changes(reader,Long.MAX_VALUE,50,noFilter).items()).extracting(ChangeHistory.Item::requestId).containsExactly("my-private");
        String hidden=jdbc.queryForObject("SELECT id FROM audit_event WHERE kind='OPERATIONS' AND request_id='other-private'",String.class);
        assertThatThrownBy(()->service.change(reader,hidden)).isInstanceOf(SecurityException.class);
    }
    @Test void latestBatchReturnsLatestAuthorizedFactOnceAndLeavesUnrecordedResourcesUnknown(){
        append();appendFor(actor,"ENTERPRISE","41","newest");
        var one=new ChangeHistory.ResourceKey("DEVICE","DEVICE","41");
        var absent=new ChangeHistory.ResourceKey("DEVICE","DEVICE","42");
        var result=service.latest(reader,List.of(one,one,absent));
        assertThat(result).hasSize(2);
        assertThat(result.get(0).latest().requestId()).isEqualTo("newest");
        assertThat(result.get(0).latest().actor().displayName()).isEqualTo("Captured Name");
        assertThat(result.get(1).latest()).isNull();
    }
    @Test void latestBatchCannotRevealOtherPrivateEditsOrRevokedResources(){
        append();appendFor(actor,"PRIVATE","41","private-later");inspectorReader();
        var key=new ChangeHistory.ResourceKey("DEVICE","DEVICE","41");
        assertThat(service.latest(reader,List.of(key))).singleElement().satisfies(item->assertThat(item.latest().requestId()).isEqualTo("change-one"));
        mayRead.set(false);assertThat(service.latest(reader,List.of(key))).isEmpty();
    }
    @Test void latestBatchRequiresExplicitActivationAndBoundedValidatedKeys(){
        var key=new ChangeHistory.ResourceKey("DEVICE","DEVICE","41");
        assertThatThrownBy(()->service.latest(reader,Collections.nCopies(101,key))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->service.latest(reader,List.of(new ChangeHistory.ResourceKey("DEVICE","DEVICE","41' OR 1=1")))).isInstanceOf(IllegalArgumentException.class);
        ReflectionTestUtils.setField(service,"changeHistoryEnabled",false);
        assertThatThrownBy(()->service.latest(reader,List.of(key))).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
    }
    @Test void relationSnapshotsKeepIdsAndNamesFromTheOperationAfterPeopleAreRenamed(){
        jdbc.update("INSERT INTO employee(id,name,employee_number,contact,department,employee_type,gender,hire_date,status) VALUES(11,'Before Name','E11','private contact','dept','DETECTION','X','2020-01-01','ACTIVE'),(12,'After Name','E12','private contact','dept','DETECTION','X','2020-01-01','ACTIVE')");
        jdbc.update("INSERT INTO device_management(id,device_code,device_type,model_name,serial_number,status,employee_id) VALUES(41,'D41','DETECTION','model','S41','IN_USE',11)");
        var snapshots=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots(jdbc);
        var mapping=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping("DEVICE","device_management","id","version",List.of("employee_id"),Set.of(),Set.of());
        tx.executeWithoutResult(status->{
            var before=snapshots.capture(mapping,"41",true);
            jdbc.update("UPDATE device_management SET employee_id=12 WHERE id=41");
            var after=snapshots.advance(mapping,before,snapshots.capture(mapping,"41",false));
            var changes=BusinessFieldChanges.compare(before,after);
            assertThat(changes).extracting(ChangeHistory.Change::field).containsExactlyInAnyOrder("employee_id","employee_name","employee_number");
            service.appendChange(new OperationsAuditApi.ChangeEvent(new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","41","reassign-name","APPLIED",after.version()),"DEVICE","Captured Name",before.version(),changes));
        });
        jdbc.update("UPDATE employee SET name='Renamed Later' WHERE id IN (11,12)");
        var latest=service.latest(reader,List.of(new ChangeHistory.ResourceKey("DEVICE","DEVICE","41"))).get(0).latest();
        assertThat(service.change(reader,latest.id()).changes()).filteredOn(change->change.field().equals("employee_name")).singleElement().satisfies(change->{
            assertThat(change.before()).isEqualTo("Before Name");assertThat(change.after()).isEqualTo("After Name");
        });
        assertThat(service.change(reader,latest.id()).changes()).filteredOn(change->change.field().equals("employee_id")).singleElement().satisfies(change->{assertThat(change.before()).isEqualTo("11");assertThat(change.after()).isEqualTo("12");});
    }
    @Test void relationSnapshotsKeepDepartmentNamesAndNeverPullContactOrCredentialFields(){
        jdbc.update("INSERT INTO organization_department(id,name) VALUES(21,'Original Department'),(22,'Next Department')");
        jdbc.update("INSERT INTO employee(id,name,employee_number,contact,department,employee_type,gender,hire_date,status,department_id) VALUES(11,'Staff','E11','private contact','dept','DETECTION','X','2020-01-01','ACTIVE',21)");
        var snapshots=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots(jdbc);
        var mapping=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping("EMPLOYEE","employee","id","version",List.of("department_id"),Set.of(),Set.of());
        var before=snapshots.capture(mapping,"11",false);
        jdbc.update("UPDATE employee SET department_id=22 WHERE id=11");var after=snapshots.capture(mapping,"11",false);
        jdbc.update("UPDATE organization_department SET name='Renamed Department' WHERE id=21");
        assertThat(before.fields()).containsEntry("department_id","21").containsEntry("department_name","Original Department").hasSize(2);
        assertThat(after.fields()).containsEntry("department_id","22").containsEntry("department_name","Next Department").hasSize(2);
    }
    @Test void appendReturnsThePersistedReceiptAndExactReplayKeepsAllIdentifiers(){
        var event=new OperationsAuditApi.ChangeEvent(new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","41","receipt-returned","APPLIED",6L),
                "DEVICE","Captured Name",5L,List.of(new ChangeHistory.Change("status","状态","REPLACE","IDLE","IN_USE","SCALAR",false)));
        var first=tx.execute(status->service.appendChangeWithReceipt(event));
        var replay=tx.execute(status->service.appendChangeWithReceipt(event));
        assertThat(replay).isEqualTo(first);assertThat(first.resourceVersion()).isEqualTo("6");
        var row=jdbc.queryForMap("SELECT id,event_id FROM audit_event WHERE kind='OPERATIONS' AND request_id='receipt-returned'");
        assertThat(first.auditId()).isEqualTo(String.valueOf(row.get("id")));assertThat(first.eventId()).isEqualTo(row.get("event_id"));
    }
    @Test void supplementalReceiptLookupCannotCrossActorsOrTheExactBusinessCommand(){
        append();
        var receipt=tx.execute(status->service.findChangeReceipt(actor,"DEVICE","DEVICE","41","change-one"));
        assertThat(receipt).isNotNull();assertThat(receipt.resourceVersion()).isEqualTo("6");
        assertThat(tx.<OperationsAuditApi.ChangeReceipt>execute(status->service.findChangeReceipt(reader,"DEVICE","DEVICE","41","change-one"))).isNull();
        assertThat(tx.<OperationsAuditApi.ChangeReceipt>execute(status->service.findChangeReceipt(actor,"DEVICE","DEVICE","42","change-one"))).isNull();
        assertThat(tx.<OperationsAuditApi.ChangeReceipt>execute(status->service.findChangeReceipt(actor,"DEVICE","DEVICE_USAGE","41","change-one"))).isNull();
        assertThat(tx.<OperationsAuditApi.ChangeReceipt>execute(status->service.findChangeReceipt(actor,"DEVICE","DEVICE","41","different"))).isNull();
        when(users.current(actor.userId(),actor.username())).thenThrow(new SecurityException("qualification revoked"));
        assertThatThrownBy(()->service.findChangeReceipt(actor,"DEVICE","DEVICE","41","change-one")).isInstanceOf(SecurityException.class);
    }
    @Test void supplementalLookupDoesNotInventVersionedReceiptsFromLegacyAudit(){
        tx.executeWithoutResult(status->service.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DEVICE","UPDATE","41","legacy-receipt","APPLIED",6L)));
        assertThat(tx.<OperationsAuditApi.ChangeReceipt>execute(status->service.findChangeReceipt(actor,"DEVICE","DEVICE","41","legacy-receipt"))).isNull();
    }
}
