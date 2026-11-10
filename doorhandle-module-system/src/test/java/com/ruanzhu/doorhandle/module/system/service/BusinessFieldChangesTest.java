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
    @Test void missingFieldAndPersistedNullHaveDifferentCreateAndDeleteSemantics(){
        var values=new LinkedHashMap<String,Object>();values.put("remarks",null);var persisted=snapshot(values);
        assertThat(BusinessFieldChanges.compare(null,persisted)).singleElement().satisfies(change->assertThat(change.operation()).isEqualTo("ADD"));
        assertThat(BusinessFieldChanges.compare(persisted,null)).singleElement().satisfies(change->assertThat(change.operation()).isEqualTo("REMOVE"));
    }
    @Test void v1PreservesSignedRevisionAndNeverInventsAnActorRole(){
        var persistence=new OperationsAuditPersistence(org.mockito.Mockito.mock(org.springframework.jdbc.core.JdbcTemplate.class));
        var old=persistence.decode(1,"{\"scope\":\"ENTERPRISE\",\"domain\":\"DEVICE\",\"result\":\"APPLIED\",\"resourceVersion\":-7,\"legacyId\":null,\"legacyCreatedAt\":null}");
        assertThat(old.resourceVersion()).isEqualTo(-7);assertThat(old.detail()).isNull();
        assertThatThrownBy(()->persistence.decode(3,"{}")).hasMessageContaining("Unregistered");
        assertThatThrownBy(()->persistence.decode(1,"{\"scope\":\"ENTERPRISE\",\"domain\":\"DEVICE\",\"result\":\"APPLIED\"}"))
                .hasMessageContaining("invalid");
    }
    @Test void auditValuesMustBeBoundedAndSecretMarkersCannotContainValues(){
        var actor=new com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change("secret","秘密","CHANGED","leak",null,"SECRET",true);
        assertThatThrownBy(()->new OperationsAuditPersistence.OperationV2("ENTERPRISE","DEVICE","APPLIED",1L,"DEVICE","alice",null,"SUPERVISOR",0L,"request",List.of(actor)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
