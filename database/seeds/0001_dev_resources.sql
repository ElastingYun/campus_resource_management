-- Synthetic rooms and seats for local development and demos.
-- Idempotent: re-running inserts nothing new and never touches business data
-- (reservations, restrictions, violations are never seeded). No real people.
INSERT INTO rooms (code, name, location, access_scope, department_id, open_time, close_time, enabled)
VALUES
    ('LIB-101', '图书馆一楼自习室', '图书馆 1F', 'campus', NULL, '08:00', '22:00', true),
    ('A-201', '第一教学楼 A201', '第一教学楼 2F', 'campus', NULL, '07:00', '22:00', true),
    ('CS-305', '计算机学院 305 自习室', '计算楼 3F', 'department', 'cs', '08:00', '23:00', true)
ON CONFLICT (code) DO NOTHING;

-- 12 seats per room: 01-04 next to fixed outlets, 05-06 next to rail outlets.
INSERT INTO seats (room_id, code, outlet_type, enabled)
SELECT r.id,
       r.code || '-' || lpad(n::text, 2, '0'),
       CASE WHEN n <= 4 THEN 'fixed' WHEN n <= 6 THEN 'rail' ELSE 'none' END,
       true
FROM rooms r
CROSS JOIN generate_series(1, 12) AS n
WHERE r.code IN ('LIB-101', 'A-201', 'CS-305')
ON CONFLICT (room_id, code) DO NOTHING;
