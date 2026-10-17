package com.ruanzhu.doorhandle.module.model.api;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import java.math.BigDecimal;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ModelAgentOperationsApiTest {
    final ModelInfoMapper mapper=mock(ModelInfoMapper.class);
    final ModelAgentReadApiImpl api=new ModelAgentReadApiImpl(mapper);
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    @BeforeAll static void metadata(){TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(),"model-operations-test"),ModelInfo.class);}
    ModelInfo row(){
        var m=new ModelInfo();m.setModelId(7);m.setModelName("六类检测");m.setVersion("v2");m.setStatus("PUBLISHED");
        m.setModelPath("PRIVATE_MODEL_PATH");m.setValidationMessage("PRIVATE_VALIDATION_TEXT");m.setCompatibilityNote("PRIVATE_COMPATIBILITY");m.setCreator("PRIVATE_OPERATOR");
        return m;
    }
    @Test void registeredMetricsPreserveZeroOneAndMissingValuesWithoutAssumingLiveResults(){
        var m=row();m.setPrecisionScore(BigDecimal.ZERO);m.setRecallScore(BigDecimal.ONE);m.setMapScore(new BigDecimal("0.925"));
        m.setAvgInferenceMs(0);m.setUsageCount(0);m.setDeploymentStrategy("CANARY");m.setCanaryPercent(0);m.setAbGroup("B");
        m.setMlopsStatus("ROLLOUT");m.setValidationStatus("PASSED");when(mapper.selectOne(any())).thenReturn(m);
        var result=api.operations(boss,7);
        assertThat(result.evaluation().precisionScore()).isEqualByComparingTo("0");assertThat(result.evaluation().recallScore()).isEqualByComparingTo("1");
        assertThat(result.evaluation().mapScore()).isEqualByComparingTo("0.925");assertThat(result.evaluation().f1Score()).isNull();
        assertThat(result.evaluation().avgInferenceMs()).isZero();assertThat(result.usage().count()).isZero();
        assertThat(result.rollout().configuredPercent()).isZero();assertThat(result.rollout().strategy()).isEqualTo("CANARY");
        assertThat(result.invalidFields()).isEmpty();assertThat(result.queriedAt()).isNotNull();
    }
    @Test void invalidNumbersAndEnumsAreHiddenAndIdentifiedWithoutInventingDefaults(){
        var m=row();m.setPrecisionScore(new BigDecimal("-0.1"));m.setRecallScore(new BigDecimal("1.1"));m.setF1Score(new BigDecimal("99"));
        m.setAvgInferenceMs(-1);m.setUsageCount(-1);m.setCanaryPercent(101);m.setRollbackFromModelId(0);
        m.setDeploymentStrategy("__proto__");m.setValidationStatus("constructor");m.setMlopsStatus("NEW_STATE");
        when(mapper.selectOne(any())).thenReturn(m);var result=api.operations(boss,7);
        assertThat(result.evaluation().precisionScore()).isNull();assertThat(result.evaluation().recallScore()).isNull();assertThat(result.evaluation().f1Score()).isNull();
        assertThat(result.evaluation().mapScore()).isNull();assertThat(result.evaluation().avgInferenceMs()).isNull();assertThat(result.usage().count()).isNull();
        assertThat(result.rollout().configuredPercent()).isNull();assertThat(result.rollout().rollbackFromModelId()).isNull();assertThat(result.rollout().strategy()).isNull();
        assertThat(result.validationStatus()).isNull();assertThat(result.mlopsStatus()).isNull();
        assertThat(result.invalidFields()).containsExactlyInAnyOrder("precisionScore","recallScore","f1Score","avgInferenceMs","usageCount","configuredPercent","rollbackFromModelId","strategy","validationStatus","mlopsStatus");
    }
    @Test void primaryKeyReadSelectsOnlyWhitelistedColumnsAndExcludesPathsAndFreeText() throws Exception {
        when(mapper.selectOne(any())).thenReturn(row());var result=api.operations(boss,7);
        assertThat(new ObjectMapper().findAndRegisterModules().writeValueAsString(result)).doesNotContain("PRIVATE_","modelPath","validationMessage","compatibilityNote","creator");
        @SuppressWarnings("unchecked") ArgumentCaptor<LambdaQueryWrapper<ModelInfo>> query=ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(mapper).selectOne(query.capture());var wrapper=query.getValue();
        assertThat(wrapper.getSqlSelect()).contains("model_id","precision_score","canary_percent").doesNotContain("model_path","validation_message","compatibility_note","creator","update_description");
        assertThat(wrapper.getSqlSegment()).contains("model_id =");assertThat(wrapper.getParamNameValuePairs().values()).containsExactly(7);
    }
    @Test void unauthorizedAndInvalidReadsNeverReachStorageAndMissingModelHasNoDetails(){
        var staff=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.operations(staff,7)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.operations(boss,0)).isInstanceOf(IllegalArgumentException.class);verifyNoInteractions(mapper);
        assertThatThrownBy(()->api.operations(boss,7)).isInstanceOfSatisfying(BusinessException.class,e->assertThat(e.getCode()).isEqualTo(404));
    }
}
