package com.ruanzhu.doorhandle.server;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableAsync;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;

@SpringBootApplication(scanBasePackages = "com.ruanzhu.doorhandle")
@EnableAsync
public class DoorHandleCatchApplication {
	
	private static final Logger logger = LoggerFactory.getLogger(DoorHandleCatchApplication.class);

	public static void main(String[] args) {
		// 在创建业务 Bean 前统一 LocalDateTime、定时任务及日志的北京时间语义。
		configureTimeZone();
		// 设置默认编码为UTF-8
		System.setProperty("file.encoding", "UTF-8");
		System.setProperty("sun.jnu.encoding", "UTF-8");
		
		// 检查命令行参数
		checkAndProcessArgs(args);
		
		// 启动SpringBoot应用
		ConfigurableApplicationContext context = SpringApplication.run(DoorHandleCatchApplication.class, args);
		
		logger.info("门把手检测系统后端已启动完成！");
	}

	static void configureTimeZone() {
		java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("Asia/Shanghai"));
	}
	
	/**
	 * 检查并处理命令行参数
	 */
	private static void checkAndProcessArgs(String[] args) {
		logger.info("启动参数: {}", Arrays.toString(args));
		
		// 检查是否包含调试模式参数
		if (Arrays.asList(args).contains("--debug")) {
			System.setProperty("debug", "true");
			logger.info("调试模式已开启");
		}
		
		// 检查是否需要初始化数据库
		if (Arrays.asList(args).contains("--init-database=true") || Arrays.asList(args).contains("--init-database")) {
			System.setProperty("init-database", "true");
			logger.info("数据库初始化模式已开启");
		}
		
		// 检查是否需要清理图片
		if (Arrays.asList(args).contains("--clean-images")) {
			cleanImages();
		}
	}
	
	/**
	 * 清理上传的图片和结果
	 */
	private static void cleanImages() {
		logger.info("开始清理图片和结果...");
		
		try {
			// 清理图片目录
			Path imagesDir = Paths.get("uploads", "images");
			if (Files.exists(imagesDir)) {
				logger.info("清理图片目录: {}", imagesDir);
				deleteDirectoryContents(imagesDir.toFile());
			}
			
			// 清理结果目录
			Path resultsDir = Paths.get("uploads", "results");
			if (Files.exists(resultsDir)) {
				logger.info("清理结果目录: {}", resultsDir);
				deleteDirectoryContents(resultsDir.toFile());
			}
			
			// 清理标注图片目录
			Path annotatedDir = Paths.get("uploads", "annotated");
			if (Files.exists(annotatedDir)) {
				logger.info("清理标注图片目录: {}", annotatedDir);
				deleteDirectoryContents(annotatedDir.toFile());
			}
			
			logger.info("图片和结果清理完成！");
		} catch (IOException e) {
			logger.error("清理图片和结果时发生错误", e);
		}
	}
	
	/**
	 * 删除目录内容，但保留目录本身
	 */
	private static void deleteDirectoryContents(File directory) throws IOException {
		if (!directory.exists() || !directory.isDirectory()) {
			return;
		}
		
		File[] files = directory.listFiles();
		if (files != null) {
			for (File file : files) {
				if (file.isDirectory()) {
					deleteDirectory(file);
				} else {
					if (!file.delete()) {
						logger.warn("无法删除文件: {}", file.getAbsolutePath());
					}
				}
			}
		}
	}
	
	/**
	 * 递归删除目录及其内容
	 */
	private static void deleteDirectory(File directory) throws IOException {
		if (!directory.exists() || !directory.isDirectory()) {
			return;
		}
		
		File[] files = directory.listFiles();
		if (files != null) {
			for (File file : files) {
				if (file.isDirectory()) {
					deleteDirectory(file);
				} else {
					if (!file.delete()) {
						logger.warn("无法删除文件: {}", file.getAbsolutePath());
					}
				}
			}
		}
		
		if (!directory.delete()) {
			logger.warn("无法删除目录: {}", directory.getAbsolutePath());
		}
	}
	
	/**
	 * 初始化运行时的一些操作
	 */
	@Bean
	public CommandLineRunner initializeSystem() {
		return args -> {
			// 确保上传目录存在
			ensureDirectoryExists("uploads/images");
			ensureDirectoryExists("uploads/results");
			ensureDirectoryExists("uploads/annotated");
			ensureDirectoryExists("uploads/models");
			
			logger.info("系统初始化完成");
		};
	}
	
	/**
	 * 确保目录存在，不存在则创建
	 */
	private void ensureDirectoryExists(String dirPath) {
		Path path = Paths.get(dirPath);
		if (!Files.exists(path)) {
			try {
				Files.createDirectories(path);
				logger.info("创建目录: {}", path.toAbsolutePath());
			} catch (IOException e) {
				logger.error("创建目录失败: {}", path.toAbsolutePath(), e);
			}
		}
	}
}
