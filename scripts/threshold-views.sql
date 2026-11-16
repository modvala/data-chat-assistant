-- Threshold views for the demographic path (ADR 0005).
-- Run as the project owner, not as dca-agent. Replace PROJECT_ID before you run it.
-- The aggregation threshold hides each group with fewer than 5 distinct user_id values.

-- Customers only: demographic counts without sales.
CREATE OR REPLACE VIEW `PROJECT_ID.dca_views.customers_threshold`
OPTIONS (
  privacy_policy = '{"aggregation_threshold_policy": {"threshold": 5, "privacy_unit_column": "user_id"}}'
)
AS
SELECT
  u.id AS user_id,
  u.age,
  u.gender,
  u.state,
  u.city,
  u.country
FROM `bigquery-public-data.thelook_ecommerce.users` AS u;

-- Customers with their order items and the product brand.
-- The Brand scope rewrite (ADR 0001) filters on brand.
CREATE OR REPLACE VIEW `PROJECT_ID.dca_views.customer_sales_threshold`
OPTIONS (
  privacy_policy = '{"aggregation_threshold_policy": {"threshold": 5, "privacy_unit_column": "user_id"}}'
)
AS
SELECT
  oi.user_id,
  oi.order_id,
  oi.sale_price,
  oi.status,
  oi.created_at,
  p.brand,
  p.category,
  u.age,
  u.gender,
  u.state,
  u.city,
  u.country
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
JOIN `bigquery-public-data.thelook_ecommerce.products` AS p ON p.id = oi.product_id
JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = oi.user_id;
