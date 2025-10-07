import { Controller, Get, Param, Post } from '@nestjs/common';

@Controller('levels')
export class LevelsController {
  @Get()
  findAll() {
    return ['Level 1', 'Level 2', 'Level 3'];
  }

  @Get('/:id')
  findById(@Param('id') id: string) {
    return { id, name: 'Level 1' };
  }

  @Post()
  create() {
    return { message: 'Level created' };
  }
}
