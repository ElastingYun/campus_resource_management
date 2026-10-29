# E-02：创建工单的成功审计接入端口

状态：**Draft / E 模块端口已实现，C 的真实适配与主应用接线未完成。** 关联 [E-02 Issue #60](https://github.com/ElastingYun/campus_resource_management/issues/60)、[Draft PR #62](https://github.com/ElastingYun/campus_resource_management/pull/62)和 C 的技术反馈。本文只描述上报 `REPORTED` 的成功审计，不批准 M3 的角色、教室准入或其他状态动作。

## 为什么需要这个端口

若先提交 `m3_tickets` 再调用 C 的审计，审计失败会留下没有成功审计的工单。E 的 `TicketAudit.record_created` 接受**同一个 SQLAlchemy Session**，在 E 插入工单后、提交事务前调用；回调失败时 E 回滚整个事务。C 现有 `AuditService.record_in_session` 可在 SQLAlchemy/PostgreSQL 事务中写入公共审计，不自行 `commit`、`rollback` 或 `close`。

```python
record_created(
    session,
    *,
    actor,       # 由可信会话构造的 TicketActor；不是客户端自报身份
    ticket_id,   # 本次新工单 UUID 字符串
    room_id,     # 已校验的规范正十进制字符串
    request_id,  # E 服务端为本次新创建生成的 UUID 字符串
    now,         # 带时区的 UTC 创建时间
)
```

建议 C 适配为 `action=m3.ticket.create`、`target=ticket_id`、`result=SUCCESS`、`before=None`、`after=REPORTED`，并记录可信主体、`room_id`、`request_id`、`now`。最终公共审计字段和值由 C/E 评审。不要把故障描述、附件、联系方式、浏览器凭据或未核实角色写入审计。

## 行为与边界

- 新工单写入与成功审计一起提交；审计或提交失败均不返回创建成功。
- 同一报修人、同一 `Idempotency-Key`、同一内容重试返回原工单，不再调用创建审计。并发重试由工单唯一约束选出一个胜者，失败方读回已提交结果。
- 缺少审计适配时，创建路由返回 `503 audit_unconfigured`；回调失败返回 `503 audit_unavailable`，工单回滚。未接入 C/B 的默认路由依旧不挂主应用。
- `request_id` 与客户端的 `Idempotency-Key` 分开；客户端不能用请求头冒充审计身份。C 可用可信主体的 UUID 映射 E 的 `TicketActor.subject_id`，但生产角色及报修权限仍按 E-OPEN 待决。
- 当前 E 的隔离测试以测试回调证明事务回滚和重试行为；它**不证明 C 的审计表已经接入**。C 的适配需要在已汇合的 PostgreSQL 迁移链上做真实同事务测试，D 再决定正式挂载和配置。

E-02 的迁移仍是 E 自有表版本，不修改 A/C 历史迁移。C/A/E 分支汇合时由 D/C/E 审查新汇合迁移和空库重放结果。
