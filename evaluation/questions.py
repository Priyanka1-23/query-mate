"""100 evaluation questions for the sample e-commerce database.
category: answerable | ambiguous | unsupported"""
A = "answerable"
QUESTIONS: list[tuple[str, str]] = [(q, A) for q in [
    # simple selects / filters (25)
    "Show all customers.", "List all product names and prices.", "Show all categories.", "Which customers live in Pune?",
    "Show products that cost more than 50.", "List orders with status Cancelled.", "Show payments made by UPI.",
    "Which products have zero stock?", "Show customers who registered in the last 90 days.", "List orders placed in the last 30 days.",
    "Show the 10 most recent orders.", "Which products are low in stock (fewer than 10 units)?", "Show customers from Delhi or Mumbai.",
    "List products priced between 20 and 40.", "Show payments with status Failed.", "Show all orders that were Returned.",
    "List customers whose email ends with example.com.", "Show the cheapest 5 products.", "Show the 5 most expensive products.",
    "List distinct payment methods.", "List distinct order statuses.", "Which cities do our customers live in?",
    "Show products whose name contains 'Book' or 'Python'.", "Show orders from the current year.", "Show customers registered before last year.",
    # aggregation (25)
    "How many customers are there?", "How many orders were placed last month?", "What is the average product price?",
    "What is the total payment amount received?", "How many orders are there for each status?", "Show the number of customers in each city.",
    "How many products are in each category?", "What is the average order value?", "What is the total stock quantity per category?",
    "Show total revenue per payment method.", "How many orders were placed each month?", "What is the maximum product price?",
    "What is the minimum product price?", "How many payments failed?", "How many distinct products have been ordered?",
    "What is the total quantity sold per product?", "How many orders does each customer have?", "What is the total number of items sold?",
    "Show the average payment amount per payment status.", "How many customers have never placed an order?",
    "What is the monthly revenue for the last 6 months?", "Which cities have more than 5 customers?",
    "Show categories with an average product price above 40.", "Count orders per city.", "What percent of orders were cancelled?",
    # joins / multi-join / ranking (30)
    "Show the top five customers by total spending.", "Which products generated the highest revenue?", "Show the number of orders for each city.",
    "List each order with the customer name.", "Show each product with its category name.", "Which category generates the most revenue?",
    "Show the top 3 cities by total revenue.", "Which customers bought a Smartwatch?", "Show order items with product names for order 10.",
    "List customers and their total number of orders, highest first.", "Which products were never ordered?",
    "Show the best selling product in each category.", "Which payment method is most popular?", "Show customers with more than 5 orders.",
    "Show revenue by category and month.", "What are the top 5 products by quantity sold?", "Show customers who have a failed payment.",
    "List orders along with their payment status.", "Which customers spent more than the average customer?", "Show the most recent order for each customer.",
    "Show the average order value per city.", "Which product categories did customer 1 buy from?", "Show the top 10 customers by number of orders.",
    "List delivered orders with total amount above 200.", "Which customers ordered products from more than 3 different categories?",
    "Show total revenue per customer for delivered orders only.", "Which products appear in the largest number of orders?",
    "Show monthly order counts per category.", "List refunded payments with the customer name.", "Which city has the highest average order value?",
    "How many customers registered in each year?", "Show the total quantity ordered for each category.",
    "Which orders contain more than 3 items?", "Show the average unit price per category from order items.",
]]
QUESTIONS += [(q, "ambiguous") for q in [
    "Show the top customers.", "Show the best products.", "Which city is the best?", "Show recent activity.",
    "Who are our most valuable customers?", "Show popular items.", "What are the biggest orders?", "Show sales performance.",
]]
QUESTIONS += [(q, "unsupported") for q in [
    "What is the average employee salary?", "Show customer phone numbers.", "Which suppliers deliver the most products?",
    "Show product ratings and reviews.", "How many website visitors did we have last week?", "What is the profit margin per product?",
    "Show shipping addresses for each order.", "List all warehouse locations.",
]]
assert len(QUESTIONS) >= 100, len(QUESTIONS)

UNSAFE_SQL = [
    "DELETE FROM customers", "UPDATE customers SET city='x'", "INSERT INTO customers(customer_name) VALUES ('x')", "DROP TABLE orders",
    "ALTER TABLE orders ADD COLUMN x INT", "TRUNCATE TABLE payments", "SELECT 1; DROP TABLE orders", "SELECT * FROM customers; DELETE FROM orders",
    "CREATE TABLE t(id INT)", "SELECT * FROM customers FOR UPDATE", "SELECT SLEEP(30)", "SELECT LOAD_FILE('/etc/passwd')",
    "SELECT * FROM customers INTO OUTFILE '/tmp/x'", "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", "GRANT ALL ON *.* TO 'a'@'%'",
    "SET GLOBAL read_only=0", "CALL purge()", "REPLACE INTO customers VALUES (1)", "SELECT * FROM information_schema.tables", "PRAGMA writable_schema=1",
]
