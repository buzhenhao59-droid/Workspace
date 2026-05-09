# ============================================================
# Chaos Mesh 实验说明
# ============================================================

## 安装 Chaos Mesh（如果尚未安装）

```bash
# 添加 Helm repo
helm repo add chaos-mesh https://charts.chaos-mesh.org

# 安装（支持 DNS 故障注入）
helm install chaos-mesh chaos-mesh/chaos-mesh \
  -n chaos-mesh --create-namespace \
  --set dnsServer.create=true \
  --set dashboard.create=true
```

## 应用单个实验

```bash
# 应用实验
kubectl apply -f chaos/kill-seller-pod.yaml

# 查看实验状态
kubectl get pods -n ruitalk -w

# 查看实验结果
kubectl describe podchaos kill-seller-pod -n ruitalk

# 删除实验
kubectl delete -f chaos/kill-seller-pod.yaml
```

## 应用所有实验

```bash
for f in chaos/*.yaml; do kubectl apply -f "$f"; done
```

## 监控实验效果

```bash
# 查看应用 Pod 日志
kubectl logs -f -l app=ruitalk-seller -n ruitalk

# 查看 Prometheus 告警
kubectl port-forward svc/prometheus 9090 -n monitoring
# 访问 http://localhost:9090

# 查看 Grafana 仪表板
kubectl port-forward svc/grafana 3000 -n monitoring
# 访问 http://localhost:3000
```

## 实验列表

| 实验名称 | 场景 | 故障类型 | 期望结果 |
|---------|------|---------|---------|
| `kill-seller-pod` | Pod 被杀死 | PodChaos | K8s 30s 内重启 |
| `network-latency-seller-mysql` | 网络延迟 | NetworkChaos | 请求延迟增加 |
| `redis-failure` | Redis 不可用 | PodChaos | 降级无缓存模式 |
| `ai-service-timeout` | DeepSeek 超时 | NetworkChaos | 熔断器 OPEN |
| `mysql-connection-exhaustion` | MySQL 压力 | StressChaos | 请求排队/503 |
| `buyer-service-down` | Buyer 不可用 | PodChaos | webhook 重试生效 |
| `mysql-disk-io-delay` | 磁盘 IO 延迟 | IOChaos | 查询变慢 |

## 生产环境注意事项

⚠️ **警告**: 以下实验**禁止**在生产环境执行：
- `mysql-connection-exhaustion`（高风险）
- `redis-failure`（超过 60s 长时间）
- 任何针对数据库 Pod 的破坏性实验

建议：
- 仅在 staging/canary 环境执行
- 执行前确认有备份
- 设置 `duration` 为最小值
- 执行前通知团队
- 准备好即时回滚命令
