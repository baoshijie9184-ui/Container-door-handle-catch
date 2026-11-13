package com.ruanzhu.doorhandle.framework.semantic;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class SemanticDocumentsTest {
    @Test void stablePublicIdentityUsesCustomUuid8AndCollectionNamespace() {
        var id=SemanticDocuments.pointId("doorhandle_memories_bge_m3_v1","legacy-memory_1");
        assertThat(id.version()).isEqualTo(8);
        assertThat(id).isEqualTo(SemanticDocuments.pointId("doorhandle_memories_bge_m3_v1","legacy-memory_1"));
        assertThat(id).isNotEqualTo(SemanticDocuments.pointId("another_collection","legacy-memory_1"));
    }
    @Test void utf8ChunkingRetainsEveryCodePointWithoutTruncatingTheSource() {
        String source="检验𠀀门把手\n".repeat(1800);
        var parts=SemanticDocuments.split(source);
        assertThat(parts).hasSizeGreaterThan(1);
        assertThat(String.join("",parts)).isEqualTo(source);
        assertThat(parts).allSatisfy(part->assertThat(part.getBytes(StandardCharsets.UTF_8).length).isLessThanOrEqualTo(7800));
    }
}
