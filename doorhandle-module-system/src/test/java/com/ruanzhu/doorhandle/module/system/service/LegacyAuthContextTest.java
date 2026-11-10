package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.service.impl.AuthServiceImpl;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.test.util.ReflectionTestUtils;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class LegacyAuthContextTest {
    final UserMapper users=mock(UserMapper.class);
    final LoginSessionService sessions=mock(LoginSessionService.class);
    final JwtUtil jwt=new JwtUtil();
    final AuthServiceImpl service=new AuthServiceImpl(mock(AuthenticationManager.class),jwt,users,sessions);
    LegacyAuthContextTest(){
        ReflectionTestUtils.setField(jwt,"secret","01234567890123456789012345678901");
        ReflectionTestUtils.setField(jwt,"expiration",300L);ReflectionTestUtils.setField(jwt,"refreshExpiration",600L);
    }
    User current(){var user=new User();user.setId(7L);user.setUsername("alice");user.setRole("SUPERVISOR");when(users.selectById(7L)).thenReturn(user);
        when(sessions.currentAccount(7,"alice")).thenReturn(new LoginEligibilityService.Eligible(user,"SUPERVISOR"));return user;}
    @Test void legacyRefreshKeepsStableContextAndChecksSuppliedPageContext(){
        current();String refresh=jwt.generateRefreshToken(7L,"alice"),context=LoginSessionService.legacyAccountContext(7,"alice");
        assertThatThrownBy(()->service.refresh(refresh,"previous-account")).isInstanceOf(AccountContextChangedException.class);
        var result=service.refresh(refresh,context);assertThat(result.getAccountContext()).isEqualTo(context);assertThat(result.getRole()).isEqualTo("SUPERVISOR");
        verify(sessions,times(2)).currentAccount(7,"alice");
    }
    @Test void disabledAccountOrChangedUsernameCannotRefreshLegacyCredentials(){
        var user=current();String refresh=jwt.generateRefreshToken(7L,"alice");user.setEnabled(false);
        assertThatThrownBy(()->service.refresh(refresh,null)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        user.setEnabled(true);user.setUsername("renamed");assertThatThrownBy(()->service.refresh(refresh,null)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }
    @Test void currentPersonnelEligibilityIsRequiredEvenWithoutDurableSessionTracking(){
        current();when(sessions.currentAccount(7,"alice")).thenThrow(new org.springframework.security.authentication.DisabledException("position revoked"));
        assertThatThrownBy(()->service.refresh(jwt.generateRefreshToken(7L,"alice"),null)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }
    @Test void legacyLogoutFencesAnOldPageButDoesNotClaimDurableRevocation(){
        String access=jwt.generateToken(7L,"alice");
        assertThatThrownBy(()->service.logout(access,null,"old-page")).isInstanceOf(AccountContextChangedException.class);
        service.logout(access,null,LoginSessionService.legacyAccountContext(7,"alice"));verify(sessions,never()).revokeAll(anyLong());
    }
    @Test void accessTokenCannotBeReplayedAtRefreshEndpoint(){
        assertThatThrownBy(()->service.refresh(jwt.generateToken(7L,"alice"),null)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        verifyNoInteractions(users);
    }
}
