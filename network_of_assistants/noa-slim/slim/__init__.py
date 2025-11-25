# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

import asyncio
import datetime
from typing import Callable
import traceback

import slim_bindings


class SLIM:
    def __init__(self, 
        slim_endpoint: str, 
        local_id: str, 
        app_id: int,
        shared_space: str, 
        opentelemetry_endpoint,
        shared_secret: str = "abcde-12345-fedcb-67890-deadc", 
        invite_list: list[str] = []):
        # init tracing

        if opentelemetry_endpoint is not None:
            slim_bindings.init_tracing(
                {
                    "log_level": "info",
                    "opentelemetry": {
                        "enabled": True,
                        "grpc": {
                            "endpoint": opentelemetry_endpoint,
                        },
                    },
                }
            )
        else:
            slim_bindings.init_tracing({"log_level": "info", "opentelemetry": {"enabled": False}})

        # Split the local IDs into their respective components
        self.local_organization, self.local_namespace, self.local_agent = (
            "noa",
            "local",
            local_id,
        )

        # Split the remote IDs into their respective components
        self.remote_organization, self.remote_namespace, self.shared_space = (
            "noa",
            "channel",
            shared_space,
        )
        
        self.app_id = app_id
        self.local_agent += str(self.app_id)
        self.shared_space += str(self.app_id)
        self.local = slim_bindings.PyName(self.local_organization, self.local_namespace, self.local_agent)
        self.channel = slim_bindings.PyName(self.remote_organization, self.remote_namespace, self.shared_space)

        self.slim_endpoint = slim_endpoint
        self.invite_list = invite_list
        self.shared_secret = shared_secret
        self.session_ready = asyncio.Event()

    async def init(self):
        provider = slim_bindings.PyIdentityProvider.SharedSecret(
            identity=str(self.local),
            shared_secret=self.shared_secret,
        )
        verifier = slim_bindings.PyIdentityVerifier.SharedSecret(
            identity=str(self.local),
            shared_secret=self.shared_secret,
        )
        
        self.app: slim_bindings.Slim = await slim_bindings.Slim.new(
            self.local, 
            provider, 
            verifier
        )
        _ = await self.app.connect({"endpoint": self.slim_endpoint, "tls": {"insecure": True}})
        
        if self.invite_list: # moderator
            print(f"Creating new group session (moderator)... {str(self.local)}")
            
            self.session = await self.app.create_session(
                slim_bindings.PySessionConfiguration.Group(
                    channel_name=self.channel,
                    max_retries=5,
                    timeout=datetime.timedelta(
                        seconds=5
                    ),
                    mls_enabled=False,
                )
            )
            
            for invitee in self.invite_list:
                invitee = invitee+str(self.app_id)
                print(f"Inviting participant: {invitee}")
                invitee_name = slim_bindings.PyName(
                    self.local_organization,
                    self.local_namespace,
                    invitee,
                    # self.app_id,
                )
                await self.app.set_route(invitee_name)
                await self.session.invite(invitee_name)
                print(f"{self.local} -> add {invitee_name} to the group")
        else: # other participant
            print(f"{self.local}: Waiting for session...")
            self.session = await self.app.listen_for_session()
            print(f"Session joined with id: {self.session.id}")
            
        self.session_ready.set()
            
    async def receive(
        self, 
        callback: Callable,
    ):
        async def background_task():
            await self.session_ready.wait()
            while True:
                try:
                    recv_session, msg_rcv = await self.session.get_message()
                    await callback(msg_rcv)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"Error receiving message: {e}")
                    traceback.print_exc()
                    break
            
        self.receive_task = asyncio.create_task(background_task())

    # async def receive1(
    #     self,
    #     callback: Coroutine,
    # ):
    #     # define the background task
    #     async def background_task():
    #         async with self.participant:
    #             while True:
    #                 try:
    #                     # receive message from session
    #                     recv_session, msg_rcv = await self.participant.receive(session=self.session_info.id)
    #                     # call the callback function
    #                     await callback(msg_rcv)
    #                 except asyncio.CancelledError:
    #                     break
    #                 except Exception as e:
    #                     print(f"Error receiving message: {e}")
    #                     break

    #     self.receive_task = asyncio.create_task(background_task())

    async def publish(self, msg: bytes):
        await self.session_ready.wait()
        while True:
            try:
                await self.session.publish(msg)
                break
            except KeyboardInterrupt:
                    # Handle Ctrl+C gracefully
                pass
            except asyncio.CancelledError:
                # Handle task cancellation gracefully
                pass
            except Exception as e:
                print(f"Error publishing message: {e}")

    # async def publish1(self, msg: bytes):
    #     await self.participant.publish(
    #         self.session_info,
    #         msg,
    #         self.remote_organization,
    #         self.remote_namespace,
    #         self.shared_space,
    #     )
