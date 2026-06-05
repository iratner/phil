import { Test, TestingModule } from '@nestjs/testing';
import { GameStateController } from './game-state.controller';

describe('GameStateController', () => {
  let controller: GameStateController;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [GameStateController],
    }).compile();

    controller = module.get<GameStateController>(GameStateController);
  });

  it('should be defined', () => {
    expect(controller).toBeDefined();
  });
});
