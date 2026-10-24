package com.ruanzhu.doorhandle.module.ai.evolution;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

class SkillSourcePolicyTest {
    private Map<String,Object> git(){return Map.of("resolvedUrl","https://github.com/example/skills/tree/"+"a".repeat(40)+"/skills/reader","commit","a".repeat(40));}
    private Map<String,Object> archive(){var value=new LinkedHashMap<String,Object>();value.put("provider","MODELSCOPE");value.put("revisionKind","CONTENT_SNAPSHOT");value.put("sourceUrl","https://modelscope.cn/skills/@example/reader");value.put("resolvedUrl","https://www.modelscope.cn/skills/@example/reader/archive/zip/master");value.put("archiveSha256","b".repeat(64));value.put("sourceVersion","snapshot-sha256:"+"b".repeat(64));value.put("commit",null);return value;}
    @Test void gitAndNativeArchivesHaveDifferentTruthfulRevisionKinds(){assertThat(SkillSourcePolicy.identity(git())).isEqualTo("github:example/skills/skills/reader");assertThat(SkillSourcePolicy.identity(archive())).isEqualTo("modelscope:@example/reader");assertThat(SkillSourcePolicy.revision(archive())).startsWith("snapshot-sha256:");}
    @Test void unprovenCrossMarketUpgradeRequiresNewInstall(){assertThatCode(()->SkillSourcePolicy.assertUpgradeCandidate(git(),"https://skills.sh/example/skills/reader")).doesNotThrowAnyException();assertThatThrownBy(()->SkillSourcePolicy.assertUpgradeCandidate(git(),"https://modelscope.cn/skills/@example/reader")).hasMessageContaining("新技能");assertThatCode(()->SkillSourcePolicy.assertUpgradeCandidate(archive(),"https://modelscope.cn/skills/@example/reader")).doesNotThrowAnyException();assertThatThrownBy(()->SkillSourcePolicy.assertUpgradeCandidate(archive(),"https://modelscope.cn/skills/@other/reader")).hasMessageContaining("同一");}
    @Test void nativeArchiveCannotClaimFakeGitCommitOrAnotherIdentity(){var value=archive();value.put("commit","c".repeat(40));assertThatThrownBy(()->SkillSourcePolicy.identity(value)).hasMessageContaining("无法核对");var invalid=archive();invalid.put("sourceIdentity","github:example/skills/reader");assertThatThrownBy(()->SkillSourcePolicy.identity(invalid)).hasMessageContaining("无法核对");}
    @Test void sourceCommitMustMatchTheResolvedImmutableUrl(){var value=new LinkedHashMap<>(git());value.put("commit","c".repeat(40));assertThatThrownBy(()->SkillSourcePolicy.identity(value)).hasMessageContaining("无法核对");}
}
