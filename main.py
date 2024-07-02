import json
import random
from typing import List, Any
from enum import Enum
import time
from uuid import uuid4
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()


class GameName(BaseModel):
    name: str


class DefaultWebSocketSession:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def send(self, data: str):
        await self.websocket.send_text(data)


class TicPieceState(Enum):
    Check = 'Check'
    Circle = 'Circle'
    Empty = '-'


class GameState(Enum):
    Circle = "Circle"
    Check = "Check"
    Draw = "Draw"
    Playing = "Playing"


class Position(BaseModel):
    x: int
    y: int
    type: TicPieceState


class ServerResponse(BaseModel):
    op: int
    data: Any


class MaxSizeException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class TicTacToe:
    def __init__(self, size: int):
        if size < 3 or size > 25:
            raise MaxSizeException("Invalid board size. Size must be between 3 and 25.")
        self.size = size
        self.board = [[TicPieceState.Empty for _ in range(size)] for _ in range(size)]

    def is_coordinate_valid(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.board[x][y] == TicPieceState.Empty

    def place_piece(self, x: int, y: int, piece: TicPieceState) -> bool:
        if not self.is_coordinate_valid(x, y):
            return False
        self.board[x][y] = piece
        return True

    def check_win(self, piece: TicPieceState) -> bool:
        for i in range(self.size):
            if all(self.board[i][j] == piece for j in range(self.size)):
                return True
            if all(self.board[j][i] == piece for j in range(self.size)):
                return True
        if all(self.board[i][i] == piece for i in range(self.size)):
            return True
        if all(self.board[i][self.size - i - 1] == piece for i in range(self.size)):
            return True
        return False

    def check_game_status(self) -> GameState:
        for row in self.board:
            if all(cell == TicPieceState.Circle for cell in row):
                return GameState.Circle
            if all(cell == TicPieceState.Check for cell in row):
                return GameState.Check
        for col in range(self.size):
            if all(row[col] == TicPieceState.Circle for row in self.board):
                return GameState.Circle
            if all(row[col] == TicPieceState.Check for row in self.board):
                return GameState.Check
        if self.check_win(TicPieceState.Circle):
            return GameState.Circle
        if self.check_win(TicPieceState.Check):
            return GameState.Check
        if all(cell != TicPieceState.Empty for row in self.board for cell in row):
            return GameState.Draw
        return GameState.Playing

    def get_board(self) -> str:
        game_board = [[cell.value for cell in row] for row in self.board]
        return json.dumps(game_board)

    def place_random_piece(self, piece: TicPieceState) -> bool:
        empty_cells = [(i, j) for i in range(self.size) for j in range(self.size) if
                       self.board[i][j] == TicPieceState.Empty]
        if empty_cells:
            x, y = random.choice(empty_cells)
            self.board[x][y] = piece
            return True
        return False


class GameSession:
    def __init__(self, name: str, board: TicTacToe):
        self.name = name
        self.players: List[DefaultWebSocketSession] = []
        self.board = board
        self.time = time.time()


game_instances = []


@app.get("/create")
async def create_game(size: int = 3, name: str = None):
    if not name:
        name = str(uuid4())
    game_instance = GameSession(name, TicTacToe(size))
    game_instances.append(game_instance)
    return JSONResponse(content=GameName(name=name).dict())


@app.websocket("/game")
async def game(websocket: WebSocket, name: str, ai: bool = False):
    await websocket.accept()
    game_instance = next((game for game in game_instances if game.name == name), None)
    if not game_instance:
        await websocket.close()
        return
    session = DefaultWebSocketSession(websocket)
    game_instance.players.append(session)
    await session.send(ServerResponse(op=0, data=game_instance.board.get_board()).json())

    try:
        while True:
            data = await websocket.receive_text()
            position = Position.parse_raw(data)
            player_type = position.type
            game_instance.board.place_piece(position.x, position.y, player_type)

            if ai:
                if player_type == TicPieceState.Check:
                    game_instance.board.place_random_piece(TicPieceState.Circle)
                else:
                    game_instance.board.place_random_piece(TicPieceState.Check)

            board_data = str(game_instance.board.get_board()).replace("Circle", "O").replace("Check", "X")
            response = ServerResponse(op=0, data=board_data).json()
            for player in game_instance.players:
                await player.send(response)

            current_state = game_instance.board.check_game_status()
            if current_state != GameState.Playing:
                end_response = ServerResponse(op=1, data=current_state.value).json()
                for player in game_instance.players:
                    await player.send(end_response)
                game_instances.remove(game_instance)
                break

            # Remove old games
            now = time.time()
            game_instances[:] = [game for game in game_instances if now - game.time < 600]

    except WebSocketDisconnect:
        game_instance.players.remove(session)
        if not game_instance.players:
            game_instances.remove(game_instance)
