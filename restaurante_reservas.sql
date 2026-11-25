-- SGBD: MySQL 8.x  |  Proyecto: Sistema de reserva de mesas (v2)
DROP DATABASE IF EXISTS restaurante_reservas;
CREATE DATABASE restaurante_reservas CHARACTER SET utf8mb4;
USE restaurante_reservas;

CREATE TABLE empleado (
  id_empleado INT AUTO_INCREMENT PRIMARY KEY,
  nombre VARCHAR(80) NOT NULL,
  codigo VARCHAR(20) NOT NULL UNIQUE,      -- DNI del empleado (o 'admin')
  rol ENUM('EMPLEADO','ADMIN') NOT NULL DEFAULT 'EMPLEADO',
  clave_hash CHAR(64),                     -- solo el administrador
  activo TINYINT NOT NULL DEFAULT 1
);
CREATE TABLE cliente (
  id_cliente INT AUTO_INCREMENT PRIMARY KEY,
  nombre VARCHAR(80) NOT NULL, dni CHAR(8) NOT NULL UNIQUE,
  telefono VARCHAR(15), email VARCHAR(80)
);
CREATE TABLE zona (
  id_zona INT AUTO_INCREMENT PRIMARY KEY,
  nombre VARCHAR(40) NOT NULL UNIQUE,
  piso INT NOT NULL
);
CREATE TABLE mesa (
  id_mesa INT AUTO_INCREMENT PRIMARY KEY,
  numero INT NOT NULL UNIQUE,
  capacidad INT NOT NULL CHECK (capacidad > 0),
  id_zona INT NOT NULL,
  FOREIGN KEY (id_zona) REFERENCES zona(id_zona)
);
CREATE TABLE reserva (
  id_reserva INT AUTO_INCREMENT PRIMARY KEY,
  id_cliente INT NOT NULL, id_mesa INT NOT NULL,
  fecha DATE NOT NULL, hora TIME NOT NULL,
  personas INT NOT NULL CHECK (personas > 0),
  observaciones VARCHAR(255) NULL,
  fecha_registro DATE NOT NULL DEFAULT (CURDATE()),
  estado ENUM('CONFIRMADA','CANCELADA','ASISTIO','NO_SHOW') NOT NULL DEFAULT 'CONFIRMADA',
  FOREIGN KEY (id_cliente) REFERENCES cliente(id_cliente),
  FOREIGN KEY (id_mesa) REFERENCES mesa(id_mesa)
);
CREATE TABLE auditoria_reserva (
  id_auditoria INT AUTO_INCREMENT PRIMARY KEY,
  id_reserva INT NOT NULL,
  estado_anterior VARCHAR(15), estado_nuevo VARCHAR(15),
  fecha_cambio DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reserva_fecha_hora ON reserva(fecha, hora);
CREATE INDEX idx_reserva_mesa ON reserva(id_mesa);
CREATE INDEX idx_reserva_cliente ON reserva(id_cliente);

DELIMITER $$
CREATE FUNCTION fn_mesa_disponible(p_fecha DATE, p_hora TIME, p_personas INT)
RETURNS INT READS SQL DATA
BEGIN
  DECLARE v_mesa INT;
  SELECT m.id_mesa INTO v_mesa FROM mesa m
  WHERE m.capacidad >= p_personas AND NOT EXISTS (
      SELECT 1 FROM reserva r WHERE r.id_mesa = m.id_mesa AND r.fecha = p_fecha
        AND r.estado IN ('CONFIRMADA','ASISTIO')
        AND ABS(TIME_TO_SEC(r.hora) - TIME_TO_SEC(p_hora)) < 7200)
  ORDER BY m.capacidad, m.id_mesa LIMIT 1;
  RETURN v_mesa;
END$$

-- p_mesa NULL = asignar automaticamente; con valor = mesa elegida en el mapa
CREATE PROCEDURE sp_crear_reserva(IN p_cliente INT, IN p_mesa INT, IN p_fecha DATE,
  IN p_hora TIME, IN p_personas INT, IN p_obs VARCHAR(255), OUT p_id INT)
BEGIN
  DECLARE v_cap INT;
  IF p_fecha < CURDATE() THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No se puede reservar en una fecha pasada';
  END IF;
  IF p_mesa IS NULL THEN
    SET p_mesa = fn_mesa_disponible(p_fecha, p_hora, p_personas);
    IF p_mesa IS NULL THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No hay mesa disponible para esa fecha, hora y cantidad de personas';
    END IF;
  ELSE
    SELECT capacidad INTO v_cap FROM mesa WHERE id_mesa = p_mesa;
    IF v_cap IS NULL OR v_cap < p_personas THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La mesa no existe o no tiene capacidad suficiente';
    END IF;
  END IF;
  INSERT INTO reserva(id_cliente, id_mesa, fecha, hora, personas, observaciones)
  VALUES (p_cliente, p_mesa, p_fecha, p_hora, p_personas, p_obs);
  SET p_id = LAST_INSERT_ID();
END$$

CREATE PROCEDURE sp_modificar_reserva(IN p_id INT, IN p_mesa INT, IN p_fecha DATE,
  IN p_hora TIME, IN p_personas INT, IN p_obs VARCHAR(255))
BEGIN
  DECLARE v_est VARCHAR(15); DECLARE v_cap INT;
  SELECT estado INTO v_est FROM reserva WHERE id_reserva = p_id;
  IF v_est IS NULL OR v_est <> 'CONFIRMADA' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se pueden modificar reservas confirmadas';
  END IF;
  SELECT capacidad INTO v_cap FROM mesa WHERE id_mesa = p_mesa;
  IF v_cap IS NULL OR v_cap < p_personas THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La mesa no existe o no tiene capacidad suficiente';
  END IF;
  UPDATE reserva SET id_mesa = p_mesa, fecha = p_fecha, hora = p_hora,
         personas = p_personas, observaciones = p_obs WHERE id_reserva = p_id;
END$$

CREATE PROCEDURE sp_cambiar_estado(IN p_id INT, IN p_estado VARCHAR(15))
BEGIN
  UPDATE reserva SET estado = p_estado WHERE id_reserva = p_id AND estado = 'CONFIRMADA';
  IF ROW_COUNT() = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se puede cambiar el estado de reservas confirmadas';
  END IF;
END$$

CREATE PROCEDURE sp_cancelar_reserva(IN p_id INT)
BEGIN
  CALL sp_cambiar_estado(p_id, 'CANCELADA');
END$$

CREATE PROCEDURE sp_eliminar_reserva(IN p_id INT)
BEGIN
  DELETE FROM reserva WHERE id_reserva = p_id;
  IF ROW_COUNT() = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La reserva no existe';
  END IF;
END$$

CREATE TRIGGER trg_reserva_validar BEFORE INSERT ON reserva FOR EACH ROW
BEGIN
  IF NEW.estado IN ('CONFIRMADA','ASISTIO') AND EXISTS (
      SELECT 1 FROM reserva r WHERE r.id_mesa = NEW.id_mesa AND r.fecha = NEW.fecha
        AND r.estado IN ('CONFIRMADA','ASISTIO')
        AND ABS(TIME_TO_SEC(r.hora) - TIME_TO_SEC(NEW.hora)) < 7200) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La mesa ya esta reservada en ese horario';
  END IF;
END$$

CREATE TRIGGER trg_reserva_validar_upd BEFORE UPDATE ON reserva FOR EACH ROW
BEGIN
  IF NEW.estado IN ('CONFIRMADA','ASISTIO') AND EXISTS (
      SELECT 1 FROM reserva r WHERE r.id_mesa = NEW.id_mesa AND r.fecha = NEW.fecha
        AND r.id_reserva <> NEW.id_reserva AND r.estado IN ('CONFIRMADA','ASISTIO')
        AND ABS(TIME_TO_SEC(r.hora) - TIME_TO_SEC(NEW.hora)) < 7200) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La mesa ya esta reservada en ese horario';
  END IF;
END$$

CREATE TRIGGER trg_reserva_auditoria AFTER UPDATE ON reserva FOR EACH ROW
BEGIN
  IF OLD.estado <> NEW.estado THEN
    INSERT INTO auditoria_reserva(id_reserva, estado_anterior, estado_nuevo)
    VALUES (NEW.id_reserva, OLD.estado, NEW.estado);
  ELSEIF OLD.fecha <> NEW.fecha OR OLD.hora <> NEW.hora OR OLD.id_mesa <> NEW.id_mesa THEN
    INSERT INTO auditoria_reserva(id_reserva, estado_anterior, estado_nuevo)
    VALUES (NEW.id_reserva, OLD.estado, 'MODIFICADA');
  END IF;
END$$

CREATE TRIGGER trg_reserva_auditoria_del AFTER DELETE ON reserva FOR EACH ROW
BEGIN
  INSERT INTO auditoria_reserva(id_reserva, estado_anterior, estado_nuevo)
  VALUES (OLD.id_reserva, OLD.estado, 'ELIMINADA');
END$$

CREATE PROCEDURE sp_carga_historica(IN p_total INT)
BEGIN
  DECLARE i INT DEFAULT 0;
  DECLARE v_fecha DATE; DECLARE v_hora TIME; DECLARE v_pers INT;
  DECLARE v_antic INT; DECLARE v_mesa INT; DECLARE v_cli INT;
  DECLARE v_p DOUBLE; DECLARE v_r DOUBLE; DECLARE v_estado VARCHAR(15);
  WHILE i < p_total DO
    SET v_fecha = DATE_SUB(CURDATE(), INTERVAL FLOOR(1 + RAND()*90) DAY);
    SET v_hora = SEC_TO_TIME((12 + FLOOR(RAND()*10)) * 3600);
    SET v_pers = 1 + FLOOR(RAND()*8);
    SET v_antic = FLOOR(RAND()*15);
    SET v_cli = 1 + FLOOR(RAND()*10);
    SET v_mesa = fn_mesa_disponible(v_fecha, v_hora, v_pers);
    IF v_mesa IS NOT NULL THEN
      SET v_p = 0.05 + IF(v_antic > 7, 0.25, 0) + IF(HOUR(v_hora) >= 20, 0.10, 0) + IF(v_pers >= 6, 0.10, 0);
      SET v_r = RAND();
      SET v_estado = IF(v_r < 0.12, 'CANCELADA', IF(v_r < 0.12 + v_p, 'NO_SHOW', 'ASISTIO'));
      INSERT INTO reserva(id_cliente, id_mesa, fecha, hora, personas, fecha_registro, estado)
      VALUES (v_cli, v_mesa, v_fecha, v_hora, v_pers, DATE_SUB(v_fecha, INTERVAL v_antic DAY), v_estado);
    END IF;
    SET i = i + 1;
  END WHILE;
END$$
DELIMITER ;

-- Administrador unico: usuario 'admin' / contraseña 'admin123' (cámbiala)
INSERT INTO empleado(nombre, codigo, rol, clave_hash)
VALUES ('Administrador', 'admin', 'ADMIN', SHA2('admin123', 256));
-- Empleados de ejemplo: reemplaza los codigos por los DNI reales (o hazlo desde la app)
INSERT INTO empleado(nombre, codigo) VALUES
('Empleado 1','11111111'), ('Empleado 2','22222222'), ('Empleado 3','33333333');

INSERT INTO cliente(nombre, dni, telefono, email) VALUES
('Ana Torres','70000001','999111001','ana@mail.com'),('Luis Ramos','70000002','999111002','luis@mail.com'),
('Carla Vega','70000003','999111003','carla@mail.com'),('Jorge Pinto','70000004','999111004','jorge@mail.com'),
('Marta Soto','70000005','999111005','marta@mail.com'),('Pedro Díaz','70000006','999111006','pedro@mail.com'),
('Lucía Rojas','70000007','999111007','lucia@mail.com'),('Diego Cruz','70000008','999111008','diego@mail.com'),
('Sofía León','70000009','999111009','sofia@mail.com'),('Raúl Mena','70000010','999111010','raul@mail.com');

-- Piso 1: Salon principal y Zona VIP | Piso 2: Terraza
INSERT INTO zona(nombre, piso) VALUES ('Salón principal',1),('Zona VIP',1),('Terraza',2);
INSERT INTO mesa(numero, capacidad, id_zona) VALUES
(1,2,1),(2,2,1),(3,4,1),(4,4,1),(5,4,1),(6,6,1),
(7,6,2),(8,8,2),(9,8,2),
(10,2,3),(11,2,3),(12,4,3),(13,4,3),(14,6,3),(15,8,3);

CALL sp_carga_historica(900);
