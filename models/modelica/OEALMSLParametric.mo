within;
model OEALMSLParametric "MIT connection model using real MSL heat-transfer components"
  parameter Modelica.Units.SI.Temperature ambient_k(min=263.15, max=333.15)=298.15;
  parameter Real radiation_area_m2(unit="m2", min=0, max=.1)=.02;
  parameter Real heat_capacities_j_per_k[6](each unit="J/K", each min=.05,
    each max=1000)={60,70,200,.5,25,100};
  parameter Real link_resistances_k_per_w[5](each unit="K/W", each min=.05,
    each max=20)={.6,.4,2,.8,1.2};
  parameter Real case_resistance_k_per_w(unit="K/W", min=.05, max=20)=2;
  input Real convection_w_per_k(unit="W/K", start=1/3);
  input Real power_w[6](each unit="W", each start=0);
  output Real configured_capacity_j_per_k[6](each unit="J/K");
  output Real configured_link_r_k_per_w[5](each unit="K/W");
  output Real configured_case_r_k_per_w(unit="K/W");
  output Real temperature_c[6](each unit="degC");
  output Real link_w[5](each unit="W");
  output Real heat_to_ambient_w(unit="W");
  output Real input_energy_j(unit="J", start=0, fixed=true);
  output Real ambient_energy_j(unit="J");
  output Real case_energy_j(unit="J", start=0, fixed=true);
  output Real convection_energy_j(unit="J", start=0, fixed=true);
  output Real radiation_energy_j(unit="J", start=0, fixed=true);
  output Real case_heat_w(unit="W");
  output Real convection_heat_w(unit="W");
  output Real radiation_heat_w(unit="W");
  output Real sigma_w_m2_k4(unit="W/(m2.K4)") = Modelica.Constants.sigma;
  Modelica.Thermal.HeatTransfer.Components.HeatCapacitor node[6](
    C=heat_capacities_j_per_k, each T(start=ambient_k, fixed=true));
  Modelica.Thermal.HeatTransfer.Components.ThermalResistor path[5](R=link_resistances_k_per_w);
  Modelica.Thermal.HeatTransfer.Components.ThermalResistor case_path(R=case_resistance_k_per_w);
  Modelica.Thermal.HeatTransfer.Components.Convection convection;
  Modelica.Thermal.HeatTransfer.Components.BodyRadiation radiation(Gr=radiation_area_m2);
  Modelica.Thermal.HeatTransfer.Sources.PrescribedHeatFlow source[6];
  Modelica.Thermal.HeatTransfer.Sources.FixedTemperature boundary(T=ambient_k);
equation
  for i in 1:6 loop
    source[i].Q_flow = power_w[i];
    connect(source[i].port, node[i].port);
    temperature_c[i] = node[i].T-273.15;
    configured_capacity_j_per_k[i] = node[i].C;
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
  connect(node[3].port, case_path.port_a);
  connect(case_path.port_b, boundary.port);
  connect(node[6].port, convection.solid);
  connect(convection.fluid, boundary.port);
  convection.Gc = convection_w_per_k;
  connect(node[6].port, radiation.port_a);
  connect(radiation.port_b, boundary.port);
  for i in 1:5 loop
    link_w[i] = path[i].Q_flow;
    configured_link_r_k_per_w[i] = path[i].R;
  end for;
  configured_case_r_k_per_w = case_path.R;
  case_heat_w = case_path.Q_flow;
  convection_heat_w = convection.Q_flow;
  radiation_heat_w = radiation.Q_flow;
  heat_to_ambient_w = case_heat_w+convection_heat_w+radiation_heat_w;
  ambient_energy_j = case_energy_j+convection_energy_j+radiation_energy_j;
  der(input_energy_j) = sum(power_w);
  der(case_energy_j) = case_heat_w;
  der(convection_energy_j) = convection_heat_w;
  der(radiation_energy_j) = radiation_heat_w;
  annotation(uses(Modelica(version="4.0.0")),
    experiment(StartTime=0, StopTime=3600, Tolerance=1e-11),
    Documentation(info="<html>Synthetic six-node RC, actual MSL Convection and BodyRadiation. Variable external Gc, fixed effective Gr. Kelvin fourth-power radiation. Configurable synthetic RC. Host may couple actual drive losses; no physical calibration.</html>"));
end OEALMSLParametric;
