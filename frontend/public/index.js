// 帮助检测前端加载问题的工具脚本
console.log('公共目录index.js已加载');

// 检查当前环境
(function() {
  console.log('当前URL:', window.location.href);
  console.log('用户代理:', navigator.userAgent);
  
  // 只在控制台记录日志，不再在页面添加状态指示器
  
  // 页面加载完成后执行
  window.addEventListener('load', function() {
    console.log('页面完全加载');
    
    // 检查Vue应用是否存在
    const appElement = document.getElementById('app');
    if (appElement) {
      console.log('App元素存在，子元素数量:', appElement.children.length);
    } else {
      console.error('未找到App元素!');
    }
  });
})(); 