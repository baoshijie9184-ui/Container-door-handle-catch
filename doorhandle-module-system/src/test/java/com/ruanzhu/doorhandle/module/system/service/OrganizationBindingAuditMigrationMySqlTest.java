package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.system.support.BindingAuditMigrationMySqlFixture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

/** Native MySQL only, inside two independently admitted empty ECS schemas. Not a renamed target fixture. */
@EnabledIfSystemProperty(named="doorhandle.binding.source.config",matches=".+")
class OrganizationBindingAuditMigrationMySqlTest {
    private BindingAuditMigrationMySqlFixture fixture;
    private JdbcTemplate source,target;
    private final ObjectMapper json=new ObjectMapper();
    private static final long LARGE_ID=9_007_199_254_740_993L;
    private static final String FIFTY_SUPPLEMENTARY=new String(Character.toChars(0x10437)).repeat(50);

    @BeforeEach void setup() throws Exception {
        fixture=new BindingAuditMigrationMySqlFixture();source=fixture.source();target=fixture.target();
        // The target cursor already belongs to a different domain; source IDs are never reused as it.
        target.update("INSERT INTO audit_event(id,event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,revision,payload_version,payload_json) "
                +"VALUES(700,'existing-knowledge-audit','KNOWLEDGE',1,1,'KNOWLEDGE','existing-doc','CREATED',1,1,?)",
                "{\"documentId\":\"existing-doc\",\"documentVersion\":1,\"action\":\"CREATED\"}");
        insert(91,901," Alice  ",991,"原主管",null,201L,1,"BIND");
        insert(92,901,"曾用名",992,"已注销主管",201L,202L,4,"REBIND");
        insert(93,901,"现用名",992,"已注销主管",202L,null,5,"UNBIND");
        // V20 did not make (user, version) unique; repeated historical versions must survive.
        insert(94,901,"现用名",992,"已注销主管",null,202L,4,"BIND");
        insert(LARGE_ID,902,FIFTY_SUPPLEMENTARY,993,FIFTY_SUPPLEMENTARY,null,Long.MAX_VALUE,Integer.MAX_VALUE,"BIND");
    }

    private void insert(long id,long user,String username,long actor,String actorName,Long before,Long after,int version,String action) {
        source.update("INSERT INTO organization_binding_audit(id,user_id,username,actor_user_id,actor_username,before_employee_id,after_employee_id,binding_version,action,created_at) "
                +"VALUES(?,?,?,?,?,?,?,?,?,'2025-01-02 03:04:05')",id,user,username,actor,actorName,before,after,version,action);
    }

    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    @Test void preservesAllTenFieldsAndReadsHistoricalOrphansThroughTheRealStore() throws Exception {
        var before=snapshot();var sourceSequence=sourceSequence();fixture.migrate("+08:00");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='ORGANIZATION_BINDING'",Long.class)).isEqualTo(5L);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM employee",Long.class)).isZero();
        var rows=new OrganizationBindingAuditStore(target).latest(901);
        assertThat(rows).hasSize(4);
        assertThat(rows).extracting(item->item.getId()).allSatisfy(id->assertThat(id).isGreaterThan(700L));
        assertThat(rows).extracting(item->item.getAction()).containsExactly("BIND","UNBIND","REBIND","BIND");
        assertThat(rows).extracting(item->item.getBindingVersion()).containsExactly(4,5,4,1);
        assertThat(rows.get(3).getUsername()).isEqualTo(" Alice  ");
        assertThat(rows.get(3).getBeforeEmployeeId()).isNull();
        assertThat(rows.get(3).getAfterEmployeeId()).isEqualTo(201L);
        assertThat(rows.get(2).getActorUserId()).isEqualTo(992L);
        assertThat(rows.get(2).getActorUsername()).isEqualTo("已注销主管");
        assertThat(rows.get(2).getBeforeEmployeeId()).isEqualTo(201L);
        assertThat(rows.get(2).getAfterEmployeeId()).isEqualTo(202L);
        assertThat(rows.get(1).getAfterEmployeeId()).isNull();
        assertThat(rows.get(3).getCreatedAt()).isEqualTo(LocalDateTime.parse("2025-01-02T03:04:05"));
        var supplementary=new OrganizationBindingAuditStore(target).latest(902).get(0);
        assertThat(supplementary.getUsername()).isEqualTo(FIFTY_SUPPLEMENTARY);
        assertThat(supplementary.getActorUsername()).isEqualTo(FIFTY_SUPPLEMENTARY);
        assertThat(supplementary.getAfterEmployeeId()).isEqualTo(Long.MAX_VALUE);
        assertThat(supplementary.getBindingVersion()).isEqualTo(Integer.MAX_VALUE);
        var evidence=json.readTree(target.queryForObject("SELECT payload_json FROM audit_event WHERE legacy_source='organization_binding_audit' AND legacy_key=?",String.class,Long.toString(LARGE_ID)));
        assertThat(evidence.size()).isEqualTo(6);
        assertThat(evidence.path("legacyId").isTextual()).isTrue();
        assertThat(evidence.path("legacyId").asText()).isEqualTo(Long.toString(LARGE_ID));
        assertThat(evidence.path("legacyCreatedAt").asText()).isEqualTo("2025-01-02 03:04:05.000000");
        assertThat(evidence.path("beforeEmployeeId").isNull()).isTrue();
        assertThat(target.queryForObject("SELECT CAST(occurred_at AS CHAR) FROM audit_event WHERE legacy_key='91' AND kind='ORGANIZATION_BINDING'",String.class))
                .isEqualTo("2025-01-01 19:04:05.000000");
        assertThat(snapshot()).isEqualTo(before);assertThat(sourceSequence()).isEqualTo(sourceSequence);assertOtherDomainPresent();
    }

    @ParameterizedTest
    @CsvSource({"+00:00,2025-01-02 03:04:05.000000","-05:30,2025-01-02 08:34:05.000000"})
    void usesTheExplicitSourceOffsetInsteadOfAssumingBeijing(String offset,String expectedUtc) throws Exception {
        var before=snapshot();fixture.migrate(offset);
        assertThat(target.queryForObject("SELECT CAST(occurred_at AS CHAR) FROM audit_event WHERE legacy_key='91' AND kind='ORGANIZATION_BINDING'",String.class)).isEqualTo(expectedUtc);
        assertThat(snapshot()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings={
            "ALTER TABLE organization_binding_audit ADD COLUMN unreviewed_field TEXT NULL",
            "ALTER TABLE organization_binding_audit DROP COLUMN action",
            "ALTER TABLE organization_binding_audit MODIFY COLUMN username VARCHAR(50) COLLATE utf8mb4_bin NOT NULL",
            "ALTER TABLE organization_binding_audit MODIFY COLUMN actor_user_id BIGINT UNSIGNED NOT NULL",
            "ALTER TABLE organization_binding_audit MODIFY COLUMN before_employee_id BIGINT NULL DEFAULT 9",
            "ALTER TABLE organization_binding_audit MODIFY COLUMN username VARCHAR(50) NULL",
            "ALTER TABLE organization_binding_audit MODIFY COLUMN created_at DATETIME(6) NOT NULL",
            "ALTER TABLE organization_binding_audit ADD UNIQUE KEY fixture_extra_unique(id,user_id)",
            "ALTER TABLE organization_binding_audit ADD CONSTRAINT fixture_extra_check CHECK(user_id>0)",
            "ALTER TABLE organization_binding_audit ADD CONSTRAINT fixture_extra_fk FOREIGN KEY(before_employee_id) REFERENCES organization_binding_audit(id)",
            "CREATE TRIGGER fixture_source_trigger BEFORE INSERT ON organization_binding_audit FOR EACH ROW SET NEW.username=NEW.username"
    })
    void rejectsUnreviewedSourceMetadataBeforeCopy(String change) {
        boolean foreignKey=change.contains("fixture_extra_fk");
        if(foreignKey) {
            // MySQL permits same-table references between different columns, not id -> itself.
            // Keep the existing signed BIGINT primary key and make the two non-null child values valid.
            assertThat(source.update("UPDATE organization_binding_audit SET before_employee_id="
                    +"CASE before_employee_id WHEN 201 THEN 91 WHEN 202 THEN 92 END WHERE before_employee_id IS NOT NULL"))
                    .isEqualTo(2);
        }
        source.execute(change);
        if(foreignKey) {
            assertThat(source.queryForObject("SELECT COUNT(*) FROM information_schema.key_column_usage "
                    +"WHERE constraint_schema=DATABASE() AND table_name='organization_binding_audit' "
                    +"AND constraint_name='fixture_extra_fk' AND column_name='before_employee_id' "
                    +"AND referenced_table_schema=DATABASE() AND referenced_table_name='organization_binding_audit' "
                    +"AND referenced_column_name='id'",Integer.class)).isEqualTo(1);
            assertThat(source.queryForObject("SELECT unique_constraint_name FROM information_schema.referential_constraints "
                    +"WHERE constraint_schema=DATABASE() AND table_name='organization_binding_audit' "
                    +"AND constraint_name='fixture_extra_fk'",String.class)).isEqualTo("PRIMARY");
            assertRejectedAndUnchanged("INSERT INTO compact_binding_guard","information_schema.table_constraints");
        } else assertRejectedAndUnchanged();
    }

    @ParameterizedTest
    @ValueSource(strings={
            "user_id=0","actor_user_id=-1","before_employee_id=-1",
            "before_employee_id=201,after_employee_id=201,action='REBIND'",
            "before_employee_id=NULL,after_employee_id=NULL,action='UNBIND'",
            "action='UNBIND'","action='bind'","action='BIND '","binding_version=0","username=''",
            "actor_username=''","created_at='9999-12-31 23:59:59'"
    })
    void rejectsUnreadableHistoricalEvidenceWithoutDiscardingAnyRow(String change) {
        source.update("UPDATE organization_binding_audit SET "+change+" WHERE id=91");assertRejectedAndUnchanged();
    }

    @ParameterizedTest
    @ValueSource(strings={
            "NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.beforeEmployeeId')",
            "NEW.payload_json=JSON_SET(NEW.payload_json,'$.username',CONCAT(JSON_UNQUOTE(JSON_EXTRACT(NEW.payload_json,'$.username')),' '))",
            "NEW.payload_json=JSON_SET(NEW.payload_json,'$.legacyId',CAST(NEW.legacy_key AS UNSIGNED))",
            "NEW.legacy_source=CONCAT(NEW.legacy_source,' ')",
            "NEW.legacy_key=CONCAT(NEW.legacy_key,' ')",
            "NEW.resource_id=CONCAT(NEW.resource_id,' ')",
            "NEW.actor_user_id=NEW.actor_user_id+1",
            "NEW.occurred_at=DATE_ADD(NEW.occurred_at,INTERVAL 1 SECOND)",
            "NEW.request_id='unexpected-request'"
    })
    void corruptTargetEvidenceCannotLeavePartialCopiedRows(String assignment) throws Exception {
        fixture.installTarget("CREATE TRIGGER fixture_corrupt_binding BEFORE INSERT ON audit_event FOR EACH ROW SET "+assignment+";");
        assertRejectedAndUnchanged();
    }

    @Test void tailReconciliationCatchesMissingNullableEvidenceAndRollsBackEarlierRows() throws Exception {
        // Corrupt only the fourth row after three valid inserts. The target JSON/shape remain valid.
        fixture.installTarget("CREATE TRIGGER fixture_corrupt_late_binding BEFORE INSERT ON audit_event FOR EACH ROW "
                +"SET NEW.payload_json=IF(NEW.legacy_key='94',JSON_REMOVE(NEW.payload_json,'$.beforeEmployeeId'),NEW.payload_json);");
        var before=snapshot();
        assertThatThrownBy(()->fixture.migrate("+08:00")).hasMessageContaining("INSERT INTO compact_binding_guard");
        assertNoCopiedRows();assertThat(snapshot()).isEqualTo(before);
    }

    @Test void refusesToAppendASecondCopyAndKeepsTheAlreadyCopiedEvidence() throws Exception {
        fixture.migrate("+08:00");
        var sourceBefore=snapshot();var targetBefore=target.queryForList("SELECT * FROM audit_event ORDER BY id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(snapshot()).isEqualTo(sourceBefore);
        assertThat(target.queryForList("SELECT * FROM audit_event ORDER BY id")).isEqualTo(targetBefore);
    }

    @Test void rejectsMissingOrInvalidSourceOffsetsBeforeAuthorizingAnyCopy() {
        assertThatThrownBy(()->fixture.migrate(null)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->fixture.migrate("Asia/Shanghai")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->fixture.migrate("+99:00")).isInstanceOf(Exception.class);assertNoCopiedRows();
    }

    private void assertRejectedAndUnchanged(String... expectedMessageFragments) {
        var before=snapshot();var sequence=sourceSequence();
        var rejection=assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        for(String fragment:expectedMessageFragments)rejection.hasMessageContaining(fragment);
        assertNoCopiedRows();assertThat(snapshot()).isEqualTo(before);assertThat(sourceSequence()).isEqualTo(sequence);
    }

    private List<Map<String,Object>> snapshot(){return source.queryForList("SELECT * FROM organization_binding_audit ORDER BY id");}
    private Long sourceSequence(){return source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='organization_binding_audit'",Long.class);}
    private void assertNoCopiedRows(){assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='ORGANIZATION_BINDING'",Long.class)).isZero();assertOtherDomainPresent();}
    private void assertOtherDomainPresent(){assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE id=700 AND event_id='existing-knowledge-audit' AND kind='KNOWLEDGE'",Long.class)).isEqualTo(1L);}
}
