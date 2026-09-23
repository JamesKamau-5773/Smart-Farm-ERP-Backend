--
-- PostgreSQL database dump
--

\restrict hyxjLFVe3ZEmcgcCoAnpnLaj3fb5M9xtgq0RCBnX3ZoQ1fLiDSecTSl5PjreFjk

-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.tenants VALUES (2, 'bahati dairy Tenant', 'single', NULL, NULL, true, '2026-07-03 16:10:56.470845+03');
INSERT INTO public.tenants VALUES (3, 'jivu super dairy Tenant', 'single', NULL, NULL, true, '2026-07-03 17:25:05.984424+03');
INSERT INTO public.tenants VALUES (4, 'popi dairy Tenant', 'single', NULL, NULL, true, '2026-07-28 18:48:46.407257+03');
INSERT INTO public.tenants VALUES (5, 'jivu farm Tenant', 'single', NULL, NULL, true, '2026-07-30 22:36:20.972897+03');
INSERT INTO public.tenants VALUES (6, 'Kamau''s Farm Tenant', 'single', NULL, NULL, true, '2026-08-08 19:56:33.799477+03');
INSERT INTO public.tenants VALUES (7, 'WhatsApp Smoke Test Tenant', 'single', NULL, NULL, true, '2026-08-20 16:32:29.727561+03');


--
-- Data for Name: farms; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.farms VALUES (2, 2, 'bahati dairy', true, '2026-07-03 16:10:56.473185+03');
INSERT INTO public.farms VALUES (3, 3, 'jivu super dairy', true, '2026-07-03 17:25:05.987986+03');
INSERT INTO public.farms VALUES (4, 4, 'popi dairy', true, '2026-07-28 18:48:46.420843+03');
INSERT INTO public.farms VALUES (5, 5, 'jivu farm', true, '2026-07-30 22:36:20.986449+03');
INSERT INTO public.farms VALUES (6, 6, 'Kamau''s Farm', true, '2026-08-08 19:56:33.802746+03');


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.users VALUES (3, 2, 'phone_254729919161', '254729919161', NULL, '254729919161', NULL, '$2b$12$tPb0wdSe3rKDIblGo10Y4..xgVN58aVZwW0E.J.2a1j8gFcjxvnli', 'FARMER', true, '2026-07-03 16:10:56.77267+03', NULL, false);
INSERT INTO public.users VALUES (10, 6, 'phone_254716003474', 'domic', NULL, '254716003474', NULL, '$2b$12$KjRkISxN69A.ODJOacJ5FedT4Eg4b/wezDlTEAWjgUHsknpvVEEEi', 'FARM_HAND', true, '2026-09-23 13:26:33.194431+03', '254716003474', true);
INSERT INTO public.users VALUES (4, 3, 'phone_254758763260', '254758763260', NULL, '254758763260', NULL, '$2b$12$JVlM.Gxmi6UX9TiiWFwSGuLrmCFWh8pi91uIMXEq.niu7i0jB39Lq', 'FARMER', true, '2026-07-03 17:25:06.278697+03', NULL, false);
INSERT INTO public.users VALUES (5, 4, 'phone_254765432123', '254765432123', NULL, '254765432123', NULL, '$2b$12$EtqJPcuexTA.u/g5Yb/hBeJeLYbsmCWKf0cRiyHalgEqEGcGzCyOi', 'FARMER', true, '2026-07-28 18:48:46.77266+03', NULL, false);
INSERT INTO public.users VALUES (6, 5, 'phone_254729919191', '254729919191', NULL, '254729919191', NULL, '$2b$12$dA67ObtqmMf/3q.LZzm.KeRatZCg8mfOR4kjetZfMpV4Tt5LlbCGC', 'FARMER', true, '2026-07-30 22:36:21.21531+03', NULL, false);
INSERT INTO public.users VALUES (7, 6, 'phone_254722263584', '254722263584', NULL, '254722263584', NULL, '$2b$12$fVkcGqxwMF53Jkl/LuiKo.A3fsCZq5E86xVEPjJLBn8lRkPeXZNZe', 'FARMER', true, '2026-08-08 19:56:34.022468+03', '254758763260', false);


--
-- Name: farms_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.farms_id_seq', 6, true);


--
-- Name: tenants_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenants_id_seq', 9, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 10, true);


--
-- PostgreSQL database dump complete
--

\unrestrict hyxjLFVe3ZEmcgcCoAnpnLaj3fb5M9xtgq0RCBnX3ZoQ1fLiDSecTSl5PjreFjk
