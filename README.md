# 微信公众号彩票开奖推送

每天晚上23:05自动推送：双色球、大乐透、排列五、七星彩开奖结果

## 部署到 Vercel（免费）

### 1. 安装 Vercel CLI
```bash
npm i -g vercel
```

### 2. 配置环境变量
在 Vercel 后台设置：
- `APPID` = 你的微信AppID
- `APPSECRET` = 你的微信AppSecret
- `TOKEN` = 自定义Token（如：lottery2024）

### 3. 部署
```bash
vercel --prod
```

### 4. 微信后台配置
- 服务器地址：`https://你的域名.vercel.app/wx`
- Token：`lottery2024`（与环境变量一致）
- 消息加解密方式：明文模式

## 接口说明

| 接口 | 说明 |
|------|------|
| GET / | 健康检查 |
| GET /wx | 微信验证接口 |
| GET /preview | 预览今日开奖数据 |
| GET /push-now?secret=push123 | 手动触发推送 |
