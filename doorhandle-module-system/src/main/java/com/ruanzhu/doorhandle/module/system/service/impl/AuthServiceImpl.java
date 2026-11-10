package com.ruanzhu.doorhandle.module.system.service.impl;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.system.dto.LoginRequest;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.service.AuthService;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import org.springframework.beans.factory.annotation.Autowired;
import com.ruanzhu.doorhandle.module.system.service.LoginSessionService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Service;

@Slf4j
@Service
public class AuthServiceImpl implements AuthService {
    private final AuthenticationManager authenticationManager;
    private final JwtUtil jwtUtil;
    private final UserMapper userMapper;
    private final LoginSessionService sessions;
    public AuthServiceImpl(AuthenticationManager manager,JwtUtil jwt,UserMapper users){this(manager,jwt,users,null);}
    @Autowired public AuthServiceImpl(AuthenticationManager manager,JwtUtil jwt,UserMapper users,LoginSessionService sessions){this.authenticationManager=manager;this.jwtUtil=jwt;this.userMapper=users;this.sessions=sessions;}

    @Override
    public LoginResponse login(LoginRequest request) {
        try {
            Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.getUsername(), request.getPassword())
            );

            UserDetails userDetails = (UserDetails) authentication.getPrincipal();
            // 获取用户详细信息
            User user = userMapper.findByUsername(userDetails.getUsername());
            if(sessions!=null&&sessions.enabled())return sessions.login(user.getId(),user.getUsername());
            String token = jwtUtil.generateToken(user.getId(), user.getUsername());
            String refreshToken = jwtUtil.generateRefreshToken(user.getId(), user.getUsername());

            LoginResponse response = new LoginResponse();
            response.setUserId(user.getId());
            response.setToken(token);
            response.setRefreshToken(refreshToken);
            response.setUsername(user.getUsername());
            response.setRole(userDetails.getAuthorities().stream().map(a->a.getAuthority()).filter(a->a.startsWith("ROLE_")).map(a->a.substring(5)).findFirst().orElseThrow());
            response.setAccountContext(LoginSessionService.legacyAccountContext(user.getId(),user.getUsername()));
            response.setEmail(user.getEmail());
            response.setPhone(user.getPhone());
            
            return response;
        } catch (BadCredentialsException e) {
            throw new BadCredentialsException("用户名或密码错误",e);
        } catch (org.springframework.security.core.AuthenticationException e) {
            throw e;
        } catch (Exception e) {
            log.error("登录异常", e);
            throw new BusinessException("系统异常，请稍后再试");
        }
    }

    @Override
    public LoginResponse refresh(String refreshToken) {
        return refresh(refreshToken,null);
    }
    @Override public LoginResponse refresh(String refreshToken,String accountContext) {
        if(sessions!=null&&sessions.enabled())return sessions.refresh(refreshToken,accountContext);
        if (refreshToken == null || !jwtUtil.validateToken(refreshToken) || !jwtUtil.isRefreshToken(refreshToken))
            throw new org.springframework.security.authentication.CredentialsExpiredException("刷新令牌无效或已过期");
        Long userId = jwtUtil.getUserIdFromToken(refreshToken);
        String username=jwtUtil.getUsernameFromToken(refreshToken);
        if(userId==null||username==null)throw new org.springframework.security.authentication.CredentialsExpiredException("刷新令牌身份无效");
        User user = userMapper.selectById(userId);
        if (user == null||!java.util.Objects.equals(username,user.getUsername())||!Boolean.TRUE.equals(user.getEnabled()))
            throw new org.springframework.security.authentication.DisabledException("账号已停用或不存在");
        String role=sessions!=null?sessions.currentAccount(userId,username).role():legacyRole(user);
        String context=LoginSessionService.legacyAccountContext(userId,username);
        if(accountContext!=null)LoginSessionService.context(context,accountContext);
        LoginResponse response = new LoginResponse();
        response.setUserId(user.getId()); response.setUsername(user.getUsername());
        response.setRole(role);response.setAccountContext(context);
        response.setToken(jwtUtil.generateToken(user.getId(), user.getUsername()));
        response.setRefreshToken(jwtUtil.generateRefreshToken(user.getId(), user.getUsername()));
        response.setEmail(user.getEmail()); response.setPhone(user.getPhone());
        return response;
    }
    @Override public void logout(String access,String refresh,String accountContext){
        if(sessions!=null&&sessions.enabled()){sessions.logout(access,refresh,accountContext);return;}
        // Cookie-only compatibility has no durable session to revoke, but supplied page context still fences account switches.
        if(accountContext!=null){
            String token=jwtUtil.validateToken(access)&&jwtUtil.isAccessToken(access)?access:refresh;
            if(token==null||!jwtUtil.validateToken(token)||(!jwtUtil.isAccessToken(token)&&!jwtUtil.isRefreshToken(token)))
                throw new org.springframework.security.authentication.CredentialsExpiredException("退出凭据无效");
            Long id=jwtUtil.getUserIdFromToken(token);String username=jwtUtil.getUsernameFromToken(token);
            if(id==null||username==null)throw new org.springframework.security.authentication.CredentialsExpiredException("退出凭据身份无效");
            LoginSessionService.context(LoginSessionService.legacyAccountContext(id,username),accountContext);
        }
    }
    private static String legacyRole(User user){
        if("SUPERVISOR".equals(user.getRole())||"INSPECTOR".equals(user.getRole()))return user.getRole();
        throw new org.springframework.security.authentication.DisabledException("账号角色不具备登录资格");
    }
}
