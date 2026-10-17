package com.ruanzhu.doorhandle.module.model.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ModelAgentReadApiImplTest {
    final ModelInfoMapper mapper=mock(ModelInfoMapper.class);
    final ModelAgentReadApiImpl api=new ModelAgentReadApiImpl(mapper);
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);

    @Test void detailRereadsCurrentReleaseStateWithoutModelFilePath() throws Exception {
        var model=new ModelInfo();model.setModelId(7);model.setModelName("六类检测");model.setVersion("v2");
        model.setStatus("DISABLED");model.setIsDefault(false);model.setModelPath("/private/model.pth");
        when(mapper.selectById(7)).thenReturn(model);
        var result=api.model(boss,7);
        assertThat(result.status()).isEqualTo("DISABLED");assertThat(result.defaultModel()).isFalse();
        assertThat(new ObjectMapper().writeValueAsString(result)).contains("六类检测").doesNotContain("/private","modelPath");
        when(mapper.selectById(7)).thenReturn(null);
        assertThatThrownBy(()->api.model(boss,7)).isInstanceOfSatisfying(BusinessException.class,e->assertThat(e.getCode()).isEqualTo(404));
    }
    @Test void inspectorCannotReadEitherResourcePathAndInvalidIdsNeverReachStorage(){
        var staff=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.model(staff,7)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.models(staff,1,10)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.model(boss,-1)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper);
    }
}
