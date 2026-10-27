within;
model OEALMSLThermal "MIT connection model using real MSL heat-transfer components"
  parameter Modelica.Units.SI.Temperature ambient_k(min=263.15, max=333.15)=298.15;
  input Real power_w[6](each unit="W", each start=0);
  output Real temperature_c[6](each unit="degC");
  output Real link_w[5](each unit="W");
  output Real heat_to_ambient_w(unit="W");
  output Real input_energy_j(unit="J", start=0, fixed=true);
  output Real ambient_energy_j(unit="J", start=0, fixed=true);
  Modelica.Thermal.HeatTransfer.Components.HeatCapacitor node[6](
    C={60,70,200,.5,25,100}, each T(start=ambient_k, fixed=true));
  Modelica.Thermal.HeatTransfer.Components.ThermalResistor path[5](R={.6,.4,2,.8,1.2});
  Modelica.Thermal.HeatTransfer.Components.ThermalResistor ambient_path[2](R={2,3});
  Modelica.Thermal.HeatTransfer.Sources.PrescribedHeatFlow source[6];
  Modelica.Thermal.HeatTransfer.Sources.FixedTemperature boundary(T=ambient_k);
equation
  for i in 1:6 loop
    source[i].Q_flow = power_w[i];
    connect(source[i].port, node[i].port);
    temperature_c[i] = node[i].T-273.15;
  end for;
  connect(node[1].port, path[1].port_a);
  connect(path[1].port_b, node[2].port);
  connect(node[2].port, path[2].port_a);
  connect(path[2].port_b, node[3].port);
  connect(node[3].port, path[3].port_a);
  connect(path[3].port_b, node[5].port);
  connect(node[4].port, path[4].port_a);
  connect(path[4].port_b, node[5].port);
  connect(node[5].port, path[5].port_a);
  connect(path[5].port_b, node[6].port);
  connect(node[3].port, ambient_path[1].port_a);
  connect(node[6].port, ambient_path[2].port_a);
  connect(ambient_path[1].port_b, boundary.port);
  connect(ambient_path[2].port_b, boundary.port);
  for i in 1:5 loop
    link_w[i] = path[i].Q_flow;
  end for;
  heat_to_ambient_w = ambient_path[1].Q_flow+ambient_path[2].Q_flow;
  der(input_energy_j) = sum(power_w);
  der(ambient_energy_j) = heat_to_ambient_w;
  annotation(uses(Modelica(version="4.0.0")),
    experiment(StartTime=0, StopTime=3600, Tolerance=1e-11),
    Documentation(info="<html>Fixed synthetic RC parameters. Six prescribed power ports. Internal K, outputs degC. MSL 4.0.0 components under BSD3, OEAL connections MIT. No motor, robot or physical calibration.</html>"));
end OEALMSLThermal;
