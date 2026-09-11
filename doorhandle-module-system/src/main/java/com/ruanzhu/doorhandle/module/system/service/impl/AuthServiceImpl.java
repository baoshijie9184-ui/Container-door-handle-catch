package com.ruanzhu.doorhandle.module.system.service.impl;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.system.dto.LoginRequest;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.service.AuthService;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {
    private final AuthenticationManager authenticationManager;
    private final JwtUtil jwtUtil;
    private final UserMapper userMapper;

    @Override
    public LoginResponse login(LoginRequest request) {
        try {
            Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.getUsername(), request.getPassword())
            );

            UserDetails userDetails = (UserDetails) authentication.getPrincipal();
            // 获取用户详细信息
            User user = userMapper.findByUsername(userDetails.getUsername());
            String token = jwtUtil.generateToken(user.getId(), user.getUsername());
            String refreshToken = jwtUtil.generateRefreshToken(user.getId(), user.getUsername());

            LoginResponse response = new LoginResponse();
            response.setUserId(user.getId());
            response.setToken(token);
            response.setRefreshToken(refreshToken);
            response.setUsername(user.getUsername());
            response.setEmail(user.getEmail());
            response.setPhone(user.getPhone());
            
            return response;
        } catch (BadCredentialsException e) {
            throw new BusinessException("用户名或密码错误");
        } catch (Exception e) {
            log.error("登录异常", e);
            throw new BusinessException("系统异常，请稍后再试");
        }
    }

    @Override
    public LoginResponse refresh(String refreshToken) {
        if (refreshToken == null || !jwtUtil.validateToken(refreshToken) || !jwtUtil.isRefreshToken(refreshToken))
            throw new BusinessException("刷新令牌无效或已过期");
        Long userId = jwtUtil.getUserIdFromToken(refreshToken);
        User user = userMapper.selectById(userId);
        if (user == null) throw new BusinessException("用户不存在");
        LoginResponse response = new LoginResponse();
        response.setUserId(user.getId()); response.setUsername(user.getUsername());
        response.setToken(jwtUtil.generateToken(user.getId(), user.getUsername()));
        response.setRefreshToken(jwtUtil.generateRefreshToken(user.getId(), user.getUsername()));
        response.setEmail(user.getEmail()); response.setPhone(user.getPhone());
        return response;
    }
}
