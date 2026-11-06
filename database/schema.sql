-- Online Food Bank Management System (INFO 2413, Option 1)
-- Based on: Data design.docx, Logical Database Requirements.docx, HR- algori.docx
-- Run order: foodbank_schema.sql, then seed_data.sql

DROP DATABASE IF EXISTS foodbank;
CREATE DATABASE foodbank CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE foodbank;

-- ---------- USERS / LOGINS ----------
-- One login table for all roles keeps auth simple (one login page, one query).
CREATE TABLE User_Account (
  User_ID        INT AUTO_INCREMENT PRIMARY KEY,
  Email          VARCHAR(255) NOT NULL UNIQUE,
  Password_Hash  VARCHAR(255) NOT NULL,          -- bcrypt hash, never plain text
  Role           ENUM('Donor','Recipient','Volunteer','Coordinator') NOT NULL,
  Is_Active      BOOLEAN NOT NULL DEFAULT TRUE,
  Created_At     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  Last_Login     DATETIME NULL
);

CREATE TABLE Coordinator (
  Coordinator_ID INT AUTO_INCREMENT PRIMARY KEY,
  User_ID        INT NOT NULL UNIQUE,
  Name           VARCHAR(100) NOT NULL,
  Phone          VARCHAR(20),
  FOREIGN KEY (User_ID) REFERENCES User_Account(User_ID) ON DELETE CASCADE
);

CREATE TABLE Donor (
  Donor_ID  INT AUTO_INCREMENT PRIMARY KEY,
  User_ID   INT NOT NULL UNIQUE,
  Name      VARCHAR(100) NOT NULL,
  Donor_Type ENUM('Individual','Business','Organization') NOT NULL DEFAULT 'Individual',
  Phone     VARCHAR(20),
  FOREIGN KEY (User_ID) REFERENCES User_Account(User_ID) ON DELETE CASCADE
);

CREATE TABLE Recipient (
  Recipient_ID      INT AUTO_INCREMENT PRIMARY KEY,
  User_ID           INT NOT NULL UNIQUE,
  Name              VARCHAR(100) NOT NULL,
  Household_Size    INT NOT NULL CHECK (Household_Size > 0),
  Phone             VARCHAR(20),
  Food_Preferences  TEXT,
  Emergency_Contact VARCHAR(150),
  Approval_Status   ENUM('Pending','Approved','Rejected') NOT NULL DEFAULT 'Pending',
  Approved_By       INT NULL,
  FOREIGN KEY (User_ID) REFERENCES User_Account(User_ID) ON DELETE CASCADE,
  FOREIGN KEY (Approved_By) REFERENCES Coordinator(Coordinator_ID) ON DELETE SET NULL
);

CREATE TABLE Volunteer (
  Volunteer_ID  INT AUTO_INCREMENT PRIMARY KEY,
  User_ID       INT NOT NULL UNIQUE,
  Name          VARCHAR(100) NOT NULL,
  Phone         VARCHAR(20),
  Picture       VARCHAR(255),
  Availability  TEXT,
  Created_By    INT NULL,
  FOREIGN KEY (User_ID) REFERENCES User_Account(User_ID) ON DELETE CASCADE,
  FOREIGN KEY (Created_By) REFERENCES Coordinator(Coordinator_ID) ON DELETE SET NULL
);

-- ---------- INVENTORY ----------
CREATE TABLE Category (
  Category_ID INT AUTO_INCREMENT PRIMARY KEY,
  Name        VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE Donation (
  Donation_ID             INT AUTO_INCREMENT PRIMARY KEY,
  Donor_ID                INT NOT NULL,
  Date_Time               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  Collected_By_Volunteer_ID INT NULL,     -- volunteer who collected the food from the donor
  Notes                   VARCHAR(255),
  FOREIGN KEY (Donor_ID) REFERENCES Donor(Donor_ID),
  FOREIGN KEY (Collected_By_Volunteer_ID) REFERENCES Volunteer(Volunteer_ID) ON DELETE SET NULL
);

CREATE TABLE Inventory_Item (
  Item_ID         INT AUTO_INCREMENT PRIMARY KEY,
  Name            VARCHAR(100) NOT NULL,
  Category_ID     INT NOT NULL,
  Quantity        DECIMAL(10,2) NOT NULL CHECK (Quantity >= 0),
  Unit            VARCHAR(20) NOT NULL,
  Expiration_Date DATE NOT NULL,
  Donation_ID     INT NOT NULL,
  Status          ENUM('Available','Reserved','Distributed','Expired') NOT NULL DEFAULT 'Available',
  Risk_Level      ENUM('OK','HIGH') NOT NULL DEFAULT 'OK',   -- set by AI check, flagged items sort to top
  FOREIGN KEY (Category_ID) REFERENCES Category(Category_ID),
  FOREIGN KEY (Donation_ID) REFERENCES Donation(Donation_ID),
  INDEX idx_status_expiry (Status, Expiration_Date)
);

-- ---------- DISTRIBUTION ----------
CREATE TABLE Distribution (
  Distribution_ID       INT AUTO_INCREMENT PRIMARY KEY,
  Recipient_ID          INT NOT NULL,
  Pickup_Date_Time      DATETIME NOT NULL,
  Status                ENUM('Scheduled','Fulfilled','Missed','Delayed') NOT NULL DEFAULT 'Scheduled',
  Given_By_Volunteer_ID INT NULL,         -- volunteer who handed the hamper to the recipient
  FOREIGN KEY (Recipient_ID) REFERENCES Recipient(Recipient_ID),
  FOREIGN KEY (Given_By_Volunteer_ID) REFERENCES Volunteer(Volunteer_ID) ON DELETE SET NULL
);

CREATE TABLE Distribution_Item (
  Distribution_ID INT NOT NULL,
  Item_ID         INT NOT NULL,
  Quantity        DECIMAL(10,2) NOT NULL CHECK (Quantity > 0),
  PRIMARY KEY (Distribution_ID, Item_ID),
  FOREIGN KEY (Distribution_ID) REFERENCES Distribution(Distribution_ID) ON DELETE CASCADE,
  FOREIGN KEY (Item_ID) REFERENCES Inventory_Item(Item_ID)
);

-- ---------- SHIFTS ----------
-- Structured availability so the coordinator can check it before assigning a shift (feature 3.4)
CREATE TABLE Volunteer_Availability (
  Availability_ID INT AUTO_INCREMENT PRIMARY KEY,
  Volunteer_ID    INT NOT NULL,
  Day_Of_Week     ENUM('Mon','Tue','Wed','Thu','Fri','Sat','Sun') NOT NULL,
  Start_Time      TIME NOT NULL,
  End_Time        TIME NOT NULL,
  FOREIGN KEY (Volunteer_ID) REFERENCES Volunteer(Volunteer_ID) ON DELETE CASCADE
);

CREATE TABLE Shift (
  Shift_ID       INT AUTO_INCREMENT PRIMARY KEY,
  Start_Time     DATETIME NOT NULL,
  End_Time       DATETIME NOT NULL,
  Task           VARCHAR(255) NOT NULL,
  Coordinator_ID INT NOT NULL,
  FOREIGN KEY (Coordinator_ID) REFERENCES Coordinator(Coordinator_ID)
);

CREATE TABLE Shift_Assignment (
  Shift_ID     INT NOT NULL,
  Volunteer_ID INT NOT NULL,
  PRIMARY KEY (Shift_ID, Volunteer_ID),
  FOREIGN KEY (Shift_ID) REFERENCES Shift(Shift_ID) ON DELETE CASCADE,
  FOREIGN KEY (Volunteer_ID) REFERENCES Volunteer(Volunteer_ID) ON DELETE CASCADE
);

-- ---------- EXPIRY + ALERTS ----------
-- Expiry table: one row per item the AI marks expired (feeds the Waste report)
CREATE TABLE Expiry_Record (
  Expiry_ID    INT AUTO_INCREMENT PRIMARY KEY,
  Item_ID      INT NOT NULL UNIQUE,
  Quantity     DECIMAL(10,2) NOT NULL,
  Expired_On   DATE NOT NULL,
  Category_ID  INT NOT NULL,
  Recorded_At  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (Item_ID) REFERENCES Inventory_Item(Item_ID),
  FOREIGN KEY (Category_ID) REFERENCES Category(Category_ID)
);

CREATE TABLE Alert (
  Alert_ID        INT AUTO_INCREMENT PRIMARY KEY,
  Type            ENUM('Expiry Risk','Delayed','Missed','Inventory Trend') NOT NULL,
  Date_Time       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  Item_ID         INT NULL,          -- set for Expiry Risk
  Distribution_ID INT NULL,          -- set for Delayed/Missed
  Message         TEXT,
  FOREIGN KEY (Item_ID) REFERENCES Inventory_Item(Item_ID) ON DELETE CASCADE,
  FOREIGN KEY (Distribution_ID) REFERENCES Distribution(Distribution_ID) ON DELETE CASCADE
);

-- Every alert email sent to coordinators/volunteers ("View Sent Emails" use case)
CREATE TABLE Email_Log (
  Email_ID   INT AUTO_INCREMENT PRIMARY KEY,
  Alert_ID   INT NULL,
  To_User_ID INT NOT NULL,
  To_Email   VARCHAR(255) NOT NULL,
  Subject    VARCHAR(255) NOT NULL,
  Body       TEXT NOT NULL,
  Written_By ENUM('Muse AI','Template') NOT NULL,   -- Template = fallback if Muse AI is unreachable
  Run_Mode   ENUM('Manual','Automatic') NOT NULL,
  Status     ENUM('Sent','Logged only','Failed') NOT NULL,
  Sent_At    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (Alert_ID) REFERENCES Alert(Alert_ID) ON DELETE SET NULL,
  FOREIGN KEY (To_User_ID) REFERENCES User_Account(User_ID) ON DELETE CASCADE
);

-- ---------- APP SETTINGS ----------
-- Demo_Date lets a coordinator pretend "today" is another day, to demo the AI expiry removal.
CREATE TABLE App_Setting (
  Setting_Key   VARCHAR(50) PRIMARY KEY,
  Setting_Value VARCHAR(255) NULL
);

-- ---------- REPORTS (2 types, per instructor feedback) ----------
CREATE TABLE Report (
  Report_ID      INT AUTO_INCREMENT PRIMARY KEY,
  Report_Type    ENUM('Donation & Distribution Summary','Inventory Waste Summary') NOT NULL,
  Report_Year    INT NOT NULL,
  Report_Month   TINYINT NULL CHECK (Report_Month BETWEEN 1 AND 12),  -- NULL = annual report
  Generated_By   INT NOT NULL,
  Generated_At   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (Generated_By) REFERENCES Coordinator(Coordinator_ID)
);

-- ---------- VIEWS (ready-made queries for search screens) ----------
-- Donation: who GAVE the food, which volunteer COLLECTED it, and every item in it
CREATE VIEW Donation_Details AS
SELECT d.Donation_ID, d.Date_Time, dn.Donor_ID, dn.Name AS Donor_Name, dn.Donor_Type,
       v.Name AS Collected_By, i.Item_ID, i.Name AS Item_Name, c.Name AS Category,
       i.Quantity, i.Unit, i.Expiration_Date, i.Status
FROM Donation d
JOIN Donor dn ON dn.Donor_ID = d.Donor_ID
LEFT JOIN Volunteer v ON v.Volunteer_ID = d.Collected_By_Volunteer_ID
JOIN Inventory_Item i ON i.Donation_ID = d.Donation_ID
JOIN Category c ON c.Category_ID = i.Category_ID;

-- Distribution: who RECEIVED the hamper, which volunteer GAVE it, and its items
CREATE VIEW Distribution_Details AS
SELECT ds.Distribution_ID, ds.Pickup_Date_Time, ds.Status, r.Recipient_ID, r.Name AS Recipient_Name,
       r.Household_Size, v.Name AS Given_By, i.Name AS Item_Name, c.Name AS Category, di.Quantity, i.Unit
FROM Distribution ds
JOIN Recipient r ON r.Recipient_ID = ds.Recipient_ID
LEFT JOIN Volunteer v ON v.Volunteer_ID = ds.Given_By_Volunteer_ID
LEFT JOIN Distribution_Item di ON di.Distribution_ID = ds.Distribution_ID
LEFT JOIN Inventory_Item i ON i.Item_ID = di.Item_ID
LEFT JOIN Category c ON c.Category_ID = i.Category_ID;

-- ---------- APP USER (least privilege) ----------
-- CREATE USER 'foodbank_app'@'localhost' IDENTIFIED BY 'change_me';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON foodbank.* TO 'foodbank_app'@'localhost';
