package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant.Snapshot;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** Pure payload contracts; execute with the project's ECS test suite. */
class BusinessFieldChangesTest {
    private Snapshot snapshot(Map<String,Object> fields){return new Snapshot("EMPLOYEE","1",0L,fields,Set.of("contact"),Set.of("model_path"));}
    @Test void comparesActualValuesBeforeIrreversibleRedaction(){
        var before=snapshot(Map.of("contact","13800001234","model_path","/private/original"));
        var after=snapshot(Map.of("contact","13900001234","model_path","/private/replacement"));
        var changes=BusinessFieldChanges.compare(before,after);
        assertThat(changes).hasSize(2);
        assertThat(changes).filteredOn(change->change.field().equals("contact")).singleElement().satisfies(change->{
            assertThat(change.before()).isEqualTo("***1234");assertThat(change.after()).isEqualTo("***1234");
        });
        assertThat(changes).filteredOn(change->change.field().equals("model_path")).singleElement().satisfies(change->{
            assertThat(change.operation()).isEqualTo("CHANGED");assertThat(change.redacted()).isTrue();
            assertThat(change.before()).isNull();assertThat(change.after()).isNull();
        });
    }
    @Test void jdbcNumberRepresentationDoesNotInventChanges(){
        assertThat(BusinessFieldChanges.compare(snapshot(Map.of("count",1)),snapshot(Map.of("count",new BigDecimal("1.0000"))))).isEmpty();
    }
    @Test void typedChangesKeepJsonNumbersBooleansAndNullDistinctFromStrings() throws Exception {
        var old=new LinkedHashMap<String,Object>();old.put("count",1);old.put("enabled",false);old.put("optional",null);
        var next=Map.<String,Object>of("count","1","enabled","false","optional","null");
        var changes=BusinessFieldChanges.compare(snapshot(old),snapshot(next));assertThat(changes).hasSize(3);
        var json=new com.fasterxml.jackson.databind.ObjectMapper().readTree(new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(changes));
        for(var change:json){String field=change.path("field").asText();assertThat(change.path("after").isTextual()).isTrue();
            switch(field){
                case "count"->{assertThat(change.path("before").isNumber()).isTrue();assertThat(change.path("after").asText()).isEqualTo("1");}
                case "enabled"->{assertThat(change.path("before").isBoolean()).isTrue();assertThat(change.path("before").asBoolean()).isFalse();}
                case "optional"->assertThat(change.path("before").isNull()).isTrue();
                default->throw new AssertionError("Unexpected diff field");
            }
        }
    }
    @Test void canonicalNumbersHaveTheSameIdentityAfterJsonRoundTrip() throws Exception {
        var first=new com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change("count","数量","REPLACE",1,1.25,"NUMBER",false);
        var equivalent=new com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change("count","数量","REPLACE",new BigDecimal("1.0000"),new BigDecimal("1.2500"),"NUMBER",false);
        var json=new com.fasterxml.jackson.databind.ObjectMapper().enable(com.fasterxml.jackson.databind.DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
        var decoded=json.readValue(json.writeValueAsString(first),com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change.class);
        assertThat(first).isEqualTo(equivalent).isEqualTo(decoded);assertThat(first.before()).isEqualTo(BigDecimal.ONE);
    }
    @Test void jdbcSnapshotsKeepLongQuantitiesNumericAndIdentityRevisionsExact(){
        var jdbc=org.mockito.Mockito.mock(org.springframework.jdbc.core.JdbcTemplate.class);
        org.mockito.Mockito.when(jdbc.queryForList(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.eq(1L)))
                .thenReturn(List.of(Map.<String,Object>of("id",1L,"owner_id",Long.MAX_VALUE,"quantity",7L,"revision",5L)));
        var mapping=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping("RECORD","business_record","id","revision",List.of("id","owner_id","quantity","revision"),Set.of(),Set.of());
        var captured=new com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots(jdbc).capture(mapping,"1",false);
        assertThat(captured.fields()).containsEntry("id","1").containsEntry("owner_id",Long.toString(Long.MAX_VALUE)).containsEntry("revision","5").containsEntry("quantity",7L);
        assertThat(captured.version()).isEqualTo(5L);
    }
    @Test void missingFieldAndPersistedNullHaveDifferentCreateAndDeleteSemantics(){
        var values=new LinkedHashMap<String,Object>();values.put("remarks",null);var persisted=snapshot(values);
        assertThat(BusinessFieldChanges.compare(null,persisted)).singleElement().satisfies(change->assertThat(change.operation()).isEqualTo("ADD"));
        assertThat(BusinessFieldChanges.compare(persisted,null)).singleElement().satisfies(change->assertThat(change.operation()).isEqualTo("REMOVE"));
    }
    @Test void v1PreservesSignedRevisionAndNeverInventsAnActorRole(){
        var persistence=new OperationsAuditPersistence(org.mockito.Mockito.mock(org.springframework.jdbc.core.JdbcTemplate.class));
        var old=persistence.decode(1,"{\"scope\":\"ENTERPRISE\",\"domain\":\"DEVICE\",\"result\":\"APPLIED\",\"resourceVersion\":-7,\"legacyId\":null,\"legacyCreatedAt\":null}");
        assertThat(old.resourceVersion()).isEqualTo(-7);assertThat(old.detail()).isNull();
        assertThatThrownBy(()->persistence.decode(4,"{}")).hasMessageContaining("Unregistered");
        assertThatThrownBy(()->persistence.decode(1,"{\"scope\":\"ENTERPRISE\",\"domain\":\"DEVICE\",\"result\":\"APPLIED\"}"))
                .hasMessageContaining("invalid");
    }
    @Test void auditValuesMustBeBoundedAndSecretMarkersCannotContainValues(){
        var actor=new com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change("secret","秘密","CHANGED","leak",null,"SECRET",true);
        assertThatThrownBy(()->new OperationsAuditPersistence.OperationV2("ENTERPRISE","DEVICE","APPLIED",1L,"DEVICE","alice",null,"SUPERVISOR",0L,"request",List.of(actor)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
