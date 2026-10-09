#!/usr/bin/env python3.7

# Copyright (c) 2019 Intel Labs
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Spawns hero car, handles steering wheel input and weather toggling.
# Minimal status window, no camera rendering.

from __future__ import print_function

import carla

import argparse
import datetime
import logging
import math
import os
import random
import sys
import weakref

if sys.version_info >= (3, 0):
    from configparser import ConfigParser
else:
    from ConfigParser import RawConfigParser as ConfigParser

try:
    import pygame
    from pygame.locals import KMOD_CTRL
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_COMMA
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_PERIOD
    from pygame.locals import K_UP
    from pygame.locals import K_DOWN
    from pygame.locals import K_LEFT
    from pygame.locals import K_RIGHT
    from pygame.locals import K_a
    from pygame.locals import K_c
    from pygame.locals import K_d
    from pygame.locals import K_m
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_s
    from pygame.locals import K_w
    from pygame.locals import K_SPACE
except ImportError:
    raise RuntimeError('cannot import pygame, make sure pygame package is installed')


# ==============================================================================
# -- Global functions ----------------------------------------------------------
# ==============================================================================


def find_weather_presets():
    result = []
    # Clear Noon
    result.append((carla.WeatherParameters(cloudiness=5.0, precipitation=0.0, sun_altitude_angle=45.0, fog_density=2.0), "Clear Noon"))
    # Very Foggy Day
    result.append((carla.WeatherParameters(cloudiness=60.0, precipitation=10.0, sun_altitude_angle=45.0, fog_density=99.0, fog_distance=0.01, fog_falloff=0.2), "Very Foggy Day"))
    # Wet Cloudy Night
    result.append((carla.WeatherParameters(cloudiness=60.0, precipitation=0.0, sun_altitude_angle=-90.0, fog_density=85.0), "Wet Cloudy Night"))
    # Very Clear Night
    result.append((carla.WeatherParameters(cloudiness=5.0, precipitation=0.0, sun_altitude_angle=-90.0, fog_density=0.0), "Very Clear Night"))
    return result


def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return (name[:truncate - 1] + u'\u2026') if len(name) > truncate else name


def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)

    if generation.lower() == "all":
        return bps

    # If the filter returns only one bp, we assume that this one needed
    # and therefore, we ignore the generation
    if len(bps) == 1:
        return bps

    try:
        int_generation = int(generation)
        # Check if generation is in available generations
        if int_generation in [1, 2, 3]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []


# ==============================================================================
# -- Default Spawn Point -------------------------------------------------------
# ==============================================================================

DEFAULT_SPAWN_POINT = carla.Transform(
    carla.Location(x=356.560211, y=-288.463104, z=156.336990),
    carla.Rotation(pitch=1.829985, yaw=-139.894669, roll=0.000000)
)


def get_initial_spawn_point(carla_map):
    """Returns the default deterministic spawn point if available in the current map;
    otherwise falls back to a campus-filtered or random spawn point."""
    all_spawns = carla_map.get_spawn_points()
    if not all_spawns:
        return carla.Transform()

    # 1. Deterministic match: look for default spawn point
    for sp in all_spawns:
        if sp.location.distance(DEFAULT_SPAWN_POINT.location) < 2.0:
            return sp

    # 2. Fallback: filter within campus bounds
    CAMPUS_BOUNDS = {'min_x': -560.0, 'max_x': 680.0, 'min_y': -550.0, 'max_y': 650.0}
    campus_spawns = [
        sp for sp in all_spawns
        if CAMPUS_BOUNDS['min_x'] <= sp.location.x <= CAMPUS_BOUNDS['max_x']
        and CAMPUS_BOUNDS['min_y'] <= sp.location.y <= CAMPUS_BOUNDS['max_y']
    ]
    if campus_spawns:
        return random.choice(campus_spawns)

    return random.choice(all_spawns)


# ==============================================================================
# -- World ---------------------------------------------------------------------
# ==============================================================================


class World(object):
    def __init__(self, carla_world, hud, actor_filter, actor_generation):
        self.world = carla_world
        self.hud = hud
        self.player = None
        self.initial_spawn_point = None
        self._weather_presets = find_weather_presets()
        self._weather_index = 0
        self.weather_preset_name = self._weather_presets[self._weather_index][1]
        self.world.set_weather(self._weather_presets[self._weather_index][0])
        self._actor_filter = actor_filter
        self._actor_generation = actor_generation
        self.restart()
        self.world.on_tick(hud.on_world_tick)

        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 1.0 / 30.0
        self.world.apply_settings(settings)

    def restart(self):
        # Get a random blueprint.
        blueprints = get_actor_blueprints(self.world, self._actor_filter, self._actor_generation)
        if not blueprints:
             raise RuntimeError(f"No blueprints found matching {self._actor_filter} with generation {self._actor_generation}")
        blueprint = random.choice(blueprints)
        blueprint.set_attribute('role_name', 'hero')
        if blueprint.has_attribute('is_invincible'):
            blueprint.set_attribute('is_invincible', 'true')
        
        # Spawn the player.
        if self.player is not None:
            self.destroy()

        if self.initial_spawn_point is None:
            self.initial_spawn_point = get_initial_spawn_point(self.world.get_map())

        spawn_point = carla.Transform(
            carla.Location(
                x=self.initial_spawn_point.location.x,
                y=self.initial_spawn_point.location.y,
                z=self.initial_spawn_point.location.z + 2.0
            ),
            carla.Rotation(
                pitch=0.0,
                yaw=self.initial_spawn_point.rotation.yaw,
                roll=0.0
            )
        )
        self.player = self.world.try_spawn_actor(blueprint, spawn_point)

        while self.player is None:
            raw_sp = get_initial_spawn_point(self.world.get_map())
            fallback_sp = carla.Transform(
                carla.Location(x=raw_sp.location.x, y=raw_sp.location.y, z=raw_sp.location.z + 2.0),
                carla.Rotation(pitch=0.0, yaw=raw_sp.rotation.yaw, roll=0.0)
            )
            self.player = self.world.try_spawn_actor(blueprint, fallback_sp)
        
        actor_type = get_actor_display_name(self.player)
        self.hud.notification(actor_type)

    def next_weather(self, reverse=False):
        self._weather_index += -1 if reverse else 1
        self._weather_index %= len(self._weather_presets)
        preset = self._weather_presets[self._weather_index]
        self.weather_preset_name = preset[1]
        self.hud.notification('Weather: %s' % preset[1])
        self.world.set_weather(preset[0])

    def tick(self, clock):
        self.hud.tick(self, clock)

    def render(self, display):
        self.hud.render(display)

    def destroy(self):
        settings = self.world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = None
        self.world.apply_settings(settings)
        if self.player is not None:
            self.player.destroy()


# ==============================================================================
# -- DualControl ---------------------------------------------------------------
# ==============================================================================


class DualControl(object):
    def __init__(self, world, start_in_autopilot):
        self._autopilot_enabled = start_in_autopilot
        self._control = carla.VehicleControl()
        self._lights = carla.VehicleLightState.NONE
        world.player.set_autopilot(self._autopilot_enabled)
        world.player.set_light_state(self._lights)
        self._steer_cache = 0.0

        # initialize steering wheel
        pygame.joystick.init()
        joystick_count = pygame.joystick.get_count()
        if joystick_count > 1:
            raise ValueError("Please Connect Just One Joystick")
        
        self._joystick = None
        if joystick_count > 0:
            self._joystick = pygame.joystick.Joystick(0)
            self._joystick.init()

        self._parser = ConfigParser()
        self._parser.read('wheel_config.ini')
        if self._joystick:
            self._steer_idx = int(self._parser.get('G923 Racing Wheel', 'steering_wheel'))
            self._throttle_idx = int(self._parser.get('G923 Racing Wheel', 'throttle'))
            self._brake_idx = int(self._parser.get('G923 Racing Wheel', 'brake'))
            self._reverse_idx = int(self._parser.get('G923 Racing Wheel', 'reverse'))
            self._handbrake_idx = int(self._parser.get('G923 Racing Wheel', 'handbrake'))

    def parse_events(self, world, clock):
        # Update internal light state from the vehicle to respect external changes (e.g. from the Bridge)
        self._lights = world.player.get_light_state()
        current_lights = self._lights

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == 0:
                    pass
                elif event.button == 3:
                    world.next_weather()
                elif self._joystick and event.button == self._reverse_idx:
                    self._control.gear = 1 if self._control.reverse else -1
            elif event.type == pygame.KEYUP:
                if event.key == K_ESCAPE or (event.key == K_q and pygame.key.get_mods() & KMOD_CTRL):
                    return True
                elif event.key == K_c:
                    world.next_weather()
                elif event.key == K_p:
                    self._autopilot_enabled = not self._autopilot_enabled
                    world.player.set_autopilot(self._autopilot_enabled)
                    world.hud.notification('Autopilot %s' % ('On' if self._autopilot_enabled else 'Off'))
                elif event.key == pygame.locals.K_l:
                    # Use 'L' key to switch between lights:
                    # Position -> LowBeam -> Fog -> Off
                    if not self._lights & carla.VehicleLightState.Position:
                        world.hud.notification("Position lights")
                        current_lights |= carla.VehicleLightState.Position
                    else:
                        if not self._lights & carla.VehicleLightState.LowBeam:
                            world.hud.notification("Low beam lights")
                            current_lights |= carla.VehicleLightState.LowBeam
                        else:
                            if not self._lights & carla.VehicleLightState.Fog:
                                world.hud.notification("Fog lights")
                                current_lights |= carla.VehicleLightState.Fog
                            else:
                                world.hud.notification("Lights off")
                                current_lights &= ~carla.VehicleLightState.Position
                                current_lights &= ~carla.VehicleLightState.LowBeam
                                current_lights &= ~carla.VehicleLightState.Fog
                elif event.key == pygame.locals.K_i:
                    current_lights ^= carla.VehicleLightState.Interior
                elif event.key == pygame.locals.K_z:
                    current_lights ^= carla.VehicleLightState.LeftBlinker
                elif event.key == pygame.locals.K_x:
                    current_lights ^= carla.VehicleLightState.RightBlinker

        if not self._autopilot_enabled:
            self._parse_vehicle_keys(pygame.key.get_pressed(), clock.get_time())
            if self._joystick:
                self._parse_vehicle_wheel()
            self._control.reverse = self._control.gear < 0

            # Set automatic control-related vehicle lights
            if self._control.brake:
                current_lights |= carla.VehicleLightState.Brake
            else: # Remove the Brake flag
                current_lights &= ~carla.VehicleLightState.Brake
            if self._control.reverse:
                current_lights |= carla.VehicleLightState.Reverse
            else: # Remove the Reverse flag
                current_lights &= ~carla.VehicleLightState.Reverse
            
            if current_lights != self._lights: # Change the light state only if necessary
                self._lights = current_lights
                world.player.set_light_state(carla.VehicleLightState(self._lights))

            world.player.apply_control(self._control)

    def _parse_vehicle_keys(self, keys, milliseconds):
        self._control.throttle = 1.0 if keys[K_UP] or keys[K_w] else 0.0
        steer_increment = 5e-4 * milliseconds
        if keys[K_LEFT] or keys[K_a]:
            self._steer_cache -= steer_increment
        elif keys[K_RIGHT] or keys[K_d]:
            self._steer_cache += steer_increment
        else:
            self._steer_cache = 0.0
        self._steer_cache = min(0.7, max(-0.7, self._steer_cache))
        self._control.steer = round(self._steer_cache, 1)
        self._control.brake = 1.0 if keys[K_DOWN] or keys[K_s] else 0.0
        self._control.hand_brake = keys[K_SPACE]

    def _parse_vehicle_wheel(self):
        numAxes = self._joystick.get_numaxes()
        jsInputs = [float(self._joystick.get_axis(i)) for i in range(numAxes)]
        jsButtons = [float(self._joystick.get_button(i)) for i in range(self._joystick.get_numbuttons())]

        K1 = 1.0
        steerCmd = K1 * math.tan(1.1 * jsInputs[self._steer_idx])

        K2 = 1.6
        throttleCmd = K2 + (2.05 * math.log10(-0.7 * jsInputs[self._throttle_idx] + 1.4) - 1.2) / 0.92
        throttleCmd = max(0, min(1, throttleCmd))

        brakeCmd = 1.6 + (2.05 * math.log10(-0.7 * jsInputs[self._brake_idx] + 1.4) - 1.2) / 0.92
        brakeCmd = max(0, min(1, brakeCmd))

        self._control.steer = steerCmd
        self._control.brake = brakeCmd
        self._control.throttle = throttleCmd
        self._control.hand_brake = bool(jsButtons[self._handbrake_idx])


# ==============================================================================
# -- HUD -----------------------------------------------------------------------
# ==============================================================================


class HUD(object):
    def __init__(self, width, height):
        self.dim = (width, height)
        font = pygame.font.Font(pygame.font.get_default_font(), 20)
        font_name = 'courier' if os.name == 'nt' else 'mono'
        fonts = [x for x in pygame.font.get_fonts() if font_name in x]
        default_font = 'ubuntumono'
        mono = default_font if default_font in fonts else fonts[0]
        mono = pygame.font.match_font(mono)
        self._font_mono = pygame.font.Font(mono, 14)
        self._notifications = FadingText(font, (width, 40), (0, height - 40))
        self.server_fps = 0
        self.frame = 0
        self.simulation_time = 0
        self._info_text = []
        self._server_clock = pygame.time.Clock()

    def on_world_tick(self, timestamp):
        self._server_clock.tick()
        self.server_fps = self._server_clock.get_fps()
        self.frame = timestamp.frame
        self.simulation_time = timestamp.elapsed_seconds

    def tick(self, world, clock):
        self._notifications.tick(world, clock)
        t = world.player.get_transform()
        v = world.player.get_velocity()
        c = world.player.get_control()
        self._info_text = [
            'Server:  % 16.0f FPS' % self.server_fps,
            'Client:  % 16.0f FPS' % clock.get_fps(),
            '',
            'Vehicle: % 20s' % get_actor_display_name(world.player, truncate=20),
            'Speed:   % 15.0f km/h' % (3.6 * math.sqrt(v.x**2 + v.y**2 + v.z**2)),
            '',
            ('Throttle:', c.throttle, 0.0, 1.0),
            ('Steer:', c.steer, -1.0, 1.0),
            ('Brake:', c.brake, 0.0, 1.0),
            ('Reverse:', c.reverse),
            'Gear:        %s' % {-1: 'R', 0: 'N'}.get(c.gear, c.gear),
            '',
            'Weather: %s' % world.weather_preset_name]

    def notification(self, text, seconds=2.0):
        self._notifications.set_text(text, seconds=seconds)

    def render(self, display):
        display.fill((0, 0, 0))
        v_offset = 4
        bar_h_offset = 100
        bar_width = 106
        for item in self._info_text:
            if isinstance(item, tuple):
                if isinstance(item[1], bool):
                    rect = pygame.Rect((bar_h_offset, v_offset + 8), (6, 6))
                    pygame.draw.rect(display, (255, 255, 255), rect, 0 if item[1] else 1)
                else:
                    rect_border = pygame.Rect((bar_h_offset, v_offset + 8), (bar_width, 6))
                    pygame.draw.rect(display, (255, 255, 255), rect_border, 1)
                    f = (item[1] - item[2]) / (item[3] - item[2])
                    if item[2] < 0.0:
                        rect = pygame.Rect((bar_h_offset + f * (bar_width - 6), v_offset + 8), (6, 6))
                    else:
                        rect = pygame.Rect((bar_h_offset, v_offset + 8), (f * bar_width, 6))
                    pygame.draw.rect(display, (255, 255, 255), rect)
                item = item[0]
            surface = self._font_mono.render(item, True, (255, 255, 255))
            display.blit(surface, (8, v_offset))
            v_offset += 18
        self._notifications.render(display)


class FadingText(object):
    def __init__(self, font, dim, pos):
        self.font = font
        self.dim = dim
        self.pos = pos
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)

    def set_text(self, text, color=(255, 255, 255), seconds=2.0):
        text_texture = self.font.render(text, True, color)
        self.surface = pygame.Surface(self.dim)
        self.seconds_left = seconds
        self.surface.fill((0, 0, 0, 0))
        self.surface.blit(text_texture, (10, 11))

    def tick(self, _, clock):
        delta_seconds = 1e-3 * clock.get_time()
        self.seconds_left = max(0.0, self.seconds_left - delta_seconds)
        self.surface.set_alpha(500.0 * self.seconds_left)

    def render(self, display):
        display.blit(self.surface, self.pos)


# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args):
    if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        print("\033[93m[WARNING] detected running on wayland, WASD control might not work as intended. If facing issues, consider switching back to x11\033[0m")

    pygame.init()
    pygame.font.init()
    world = None
    traffic_manager = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)
        traffic_manager = client.get_trafficmanager()
        traffic_manager.set_synchronous_mode(True)

        display = pygame.display.set_mode(
            (args.width, args.height),
            pygame.HWSURFACE | pygame.DOUBLEBUF)

        hud = HUD(args.width, args.height)
        world = World(client.get_world(), hud, args.filter, args.generation)
        controller = DualControl(world, args.autopilot)

        target_fps = 30
        clock = pygame.time.Clock()
        while True:
            world.world.tick()
            clock.tick_busy_loop(target_fps)
            if controller.parse_events(world, clock):
                return
            world.tick(clock)
            world.render(display)
            pygame.display.flip()

    finally:
        if traffic_manager is not None:
            traffic_manager.set_synchronous_mode(False)
        if world is not None:
            world.destroy()
        pygame.quit()


def main():
    argparser = argparse.ArgumentParser(description='CARLA Steering Control Client')
    argparser.add_argument('--host', metavar='H', default='127.0.0.1', help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument('-p', '--port', metavar='P', default=2000, type=int, help='TCP port to listen to (default: 2000)')
    argparser.add_argument('-a', '--autopilot', action='store_true', help='enable autopilot')
    argparser.add_argument('--res', metavar='WIDTHxHEIGHT', default='400x300', help='window resolution (default: 400x300)')
    argparser.add_argument('--filter', metavar='PATTERN', default='vehicle.mini*', help='actor filter (default: "vehicle.mini*")')
    argparser.add_argument('--generation', metavar='G', default='2', help='restrict to certain actor generation (values: "1","2","All" - default: "2")')
    args = argparser.parse_args()
    args.width, args.height = [int(x) for x in args.res.split('x')]

    try:
        game_loop(args)
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')


if __name__ == '__main__':
    main()
